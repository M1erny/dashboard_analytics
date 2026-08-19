"""A missing market snapshot and an empty retrieval must be reported, not absorbed.

The reported symptom was an answer stating that live market data "was not fetched
or provided in the configuration" for a question that explicitly asked about
performance and risk. The fetch had been requested; it just did not arrive, and
the prompt described that failure as a decision. An answer that says a broken
pipeline was a design choice is worse than an error, because it reads as normal.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  [FAIL] {name} {detail}")


def main():
    print("=" * 70)
    print("BRAIN CONTEXT GAPS")
    print("=" * 70)

    # 1. The question that produced the report does ask for market data, so the
    #    empty snapshot was a failed fetch and never an intent miss. If this ever
    #    stops holding, the fix below is aimed at the wrong thing.
    reported = "Analyze my portfolio performance, construction, risk etc like munger or buffet"
    intent = server._brain_market_data_intent(reported)
    check("the reported question requests market data", intent["requested"], str(intent))
    check("and is not read as an opt-out", not intent["explicitlyDisabled"], str(intent))

    for question, expected in (
        ("What is the strongest bear case in my research?", False),
        ("Which holdings create the most concentration risk today?", True),
        ("Summarise the Damodaran framework, documents only", False),
        ("How is my YTD contribution split between longs and shorts?", True),
    ):
        got = server._brain_market_data_intent(question)["requested"]
        check(f"intent for {question[:38]!r} is {expected}", got == expected, f"got {got}")

    # 2. Three states, three different things said. The failure case is the one
    #    that was missing.
    live = server._market_data_guidance(True, None)
    skipped = server._market_data_guidance(False, None)
    failed = server._market_data_guidance(False, "the market-data fetch did not finish within 70s")

    check("a live snapshot gets the full ranking guidance", "MANDATORY RANKING FACTS" in live)
    check("a skipped fetch is described as intentional", "intentionally not fetched" in skipped)
    check(
        "a failed fetch is NOT described as intentional",
        "intentionally" not in failed,
        failed[:120],
    )
    check("a failed fetch says the fetch failed", "FETCH FAILED" in failed, failed[:120])
    check("and carries the reason", "did not finish within 70s" in failed, failed[:160])
    check(
        "and forbids inventing the missing figures",
        "do not" in failed.lower() and "invent" in failed.lower(),
        failed[:200],
    )
    check("the three states are all different", len({live, skipped, failed}) == 3)

    # 3. The heading the model sees must not read the same either.
    titles = {
        "live": server._portfolio_context_title(True, None),
        "skipped": server._portfolio_context_title(False, None),
        "failed": server._portfolio_context_title(False, "boom"),
    }
    check("titles differ across the three states", len(set(titles.values())) == 3, str(titles))
    check("the failed title says so", "FAILED" in titles["failed"], titles["failed"])
    check("the skipped title does not", "FAILED" not in titles["skipped"], titles["skipped"])

    # 4. An empty retrieval is either an empty library or an unembedded one, and
    #    those need opposite actions from the owner.
    check(
        "no passages at all is named as such",
        server._index_gap_reason({"total": 0, "embedded": 0, "missing": 0})
        == "the brain holds no indexed passages at all",
    )
    nothing_embedded = server._index_gap_reason({"total": 12480, "embedded": 0, "missing": 12480})
    check(
        "an unembedded library is named, with its size",
        nothing_embedded is not None and "12,480" in nothing_embedded and "embedded" in nothing_embedded,
        str(nothing_embedded),
    )
    partial = server._index_gap_reason({"total": 100, "embedded": 60, "missing": 40})
    check(
        "a partly embedded library reports the shortfall",
        partial is not None and "40" in partial and "100" in partial,
        str(partial),
    )
    check(
        "a fully embedded library reports no gap",
        server._index_gap_reason({"total": 100, "embedded": 100, "missing": 0}) is None,
    )
    # Not knowing is not the same claim as knowing the library is empty, and only
    # one of them is safe to print under an answer.
    check("a missing stats payload makes no claim", server._index_gap_reason(None) is None)
    check("nor does an empty one", server._index_gap_reason({}) is None)
    check(
        "but an explicit zero does",
        server._index_gap_reason({"total": 0}) == "the brain holds no indexed passages at all",
    )

    # 5. The bound on the slowest step in the request exists and is sane. Without
    #    it the market fetch can outlive the host's patience for an open
    #    connection, and the question dies with no response at all.
    timeout = server.BRAIN_PORTFOLIO_CONTEXT_TIMEOUT_SECONDS
    check("the portfolio fetch is time-boxed", 10.0 <= timeout <= 180.0, str(timeout))
    check(
        "and the box is shorter than the client's patience",
        timeout < 90.0,
        f"{timeout}s vs the frontend's 90s ask timeout",
    )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All brain context gap checks passed.")


if __name__ == "__main__":
    main()
