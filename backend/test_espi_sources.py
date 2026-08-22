"""Joining a Polish filing to a holding is name matching, and it must be strict.

The portfolio carries `LPP.WA`. An ESPI filing carries `Skrócona nazwa emitenta`
— a human abbreviation like `CDPROJEKT`. Nothing links them, so the join is name
comparison, and a wrong issuer on a regulatory filing is worse than a missed one.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espi_sources as espi

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  [FAIL] {name} {detail}")


def main():
    print("=" * 70)
    print("ESPI SOURCES")
    print("=" * 70)

    # 1. URLs. The endpoint treats a bare end date as midnight, which returns an
    #    empty day, so the time component is load-bearing.
    url = espi.search_page_url(date(2026, 8, 21))
    check("the search URL carries the day", "created=2026-08-21" in url, url)
    check("and an end time, not just a date", "23%3A59" in url, url)
    check("and a page", url.endswith("page=0"), url)
    check("page 3 is addressable", espi.search_page_url(date(2026, 8, 21), 3).endswith("page=3"))

    check("a node id becomes a permalink", espi.node_url(123456) == "https://espiebi.pap.pl/node/123456")
    check("a node path is accepted too", espi.node_url("/node/99") == "https://espiebi.pap.pl/node/99")
    for bad in ("", "abc", "node/", "../etc/passwd"):
        try:
            espi.node_url(bad)
        except ValueError:
            check(f"a non-numeric node id {bad!r} is refused", True)
        else:
            check(f"a non-numeric node id {bad!r} is refused", False, "no ValueError")

    check("a relative href resolves", espi.absolute_url("/node/5") == "https://espiebi.pap.pl/node/5")
    check("an absolute href is left alone", espi.absolute_url("https://x.test/a") == "https://x.test/a")

    # 2. Normalisation has to survive diacritics, case, punctuation and legal form,
    #    because the two sides of the join differ in all four.
    cases = [
        ("CD PROJEKT S.A.", "cdprojekt"),
        ("CDPROJEKT", "cdprojekt"),
        ("LPP SA", "lpp"),
        ("LPP", "lpp"),
        ("Benefit Systems S.A.", "benefitsystems"),
        ("BENEFITSYSTEMS", "benefitsystems"),
        ("Pepco Group N.V.", "pepco"),
        ("Agora S.A.", "agora"),
        ("Żywiec Spółka Akcyjna", "zywiec"),
        ("Grupa Kęty S.A.", "kety"),
        ("  spyrosoft   s.a.  ", "spyrosoft"),
    ]
    for raw, expected in cases:
        got = espi.normalise_issuer_name(raw)
        check(f"{raw!r} -> {expected!r}", got == expected, f"got {got!r}")
    check("an empty name normalises to empty", espi.normalise_issuer_name("") == "")
    check("a name of only a legal form normalises to empty", espi.normalise_issuer_name("S.A.") == "")

    # 3. Matching across the two naming conventions.
    check("abbreviation matches long name", espi.issuer_matches("CDPROJEKT", "CD Projekt S.A."))
    check("long name matches abbreviation", espi.issuer_matches("Benefit Systems S.A.", "BENEFITSYSTEMS"))
    check("identical short names match", espi.issuer_matches("XTB", "XTB S.A."))
    check("a prefix of four or more matches", espi.issuer_matches("PEPCO", "Pepco Group N.V."))

    # The strictness is the point: these must NOT match.
    check("AGORA does not match AGROTON", not espi.issuer_matches("AGORA", "Agroton Public Ltd"))
    check("LPP does not match a different issuer", not espi.issuer_matches("LPP", "Lubawa S.A."))
    check("a three-letter prefix is not enough", not espi.issuer_matches("BUD", "Budimex SA"))
    check("empty never matches", not espi.issuer_matches("", "LPP"))
    check("empty never matches, either side", not espi.issuer_matches("LPP", ""))

    # 4. Ticker resolution. Names are supplied by the caller — this module never
    #    guesses a company name.
    names = {
        "LPP.WA": "LPP SA",
        "CDR.WA": "CD Projekt S.A.",
        "XTB.WA": "XTB S.A.",
        "BFT.WA": "Benefit Systems S.A.",
        "AGO.WA": "Agora S.A.",
    }
    check("a filing maps to its ticker", espi.match_ticker("CDPROJEKT", names) == "CDR.WA")
    check("and to another", espi.match_ticker("Benefit Systems S.A.", names) == "BFT.WA")
    check("a filing from outside the book maps to nothing", espi.match_ticker("ORLEN", names) is None)
    check("an empty issuer maps to nothing", espi.match_ticker("", names) is None)
    check("an empty book maps to nothing", espi.match_ticker("LPP", {}) is None)

    # Ambiguity returns None rather than a coin flip: two issuers answering to one
    # abbreviation is exactly when a guess files a report under the wrong holding.
    ambiguous = {"AAA.WA": "Kruk S.A.", "BBB.WA": "Kruk Group S.A."}
    check("an ambiguous match is refused", espi.match_ticker("KRUK", ambiguous) is None, str(ambiguous))

    # 5. Badge and title classification.
    check("an ESPI badge is read", espi.classify_source("ESPI") == "ESPI")
    check("an EBI badge is read", espi.classify_source(" ebi ") == "EBI")
    check("an unknown badge is named unknown", espi.classify_source("news") == "UNKNOWN")
    check("a missing badge does not crash", espi.classify_source(None) == "UNKNOWN")

    for title in (
        "Raport roczny za 2025 rok",
        "Skonsolidowany raport kwartalny za III kwartał 2026",
        "Raport półroczny 2026",
        "Sprawozdanie finansowe za 2025",
    ):
        check(f"periodic: {title[:40]!r}", espi.is_periodic_report(title), title)
    for title in (
        "Zawiadomienie o zmianie udziału w ogólnej liczbie głosów",
        "Powołanie członka zarządu",
        "Zawarcie umowy znaczącej",
    ):
        check(f"not periodic: {title[:40]!r}", not espi.is_periodic_report(title), title)

    # 6. The official-domain set is what gates a trusted import, so it must not
    #    quietly include a blog.
    for domain in ("espiebi.pap.pl", "www.gpw.pl", "newconnect.pl", "www.knf.gov.pl"):
        check(f"{domain} is trusted", domain in espi.POLISH_OFFICIAL_DOMAINS)
    for domain in ("bankier.pl", "www.biznesradar.pl", "stockwatch.pl", "example.com"):
        check(f"{domain} is not trusted", domain not in espi.POLISH_OFFICIAL_DOMAINS)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        sys.exit(1)
    print("All ESPI source checks passed.")


if __name__ == "__main__":
    main()
