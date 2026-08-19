"""The benchmark tiles must report the benchmark, not the benchmark times FX.

ETFBW20TR.WA is both the Polish benchmark and a held position. Positions are
normalised to USD; benchmarks must not be. Before this was separated, the
"WIG20" tile compounded the index move with the PLN/USD move — in a year the
zloty ran hard that is several points of pure currency printed as an index
return.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import risk

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  [FAIL] {name} {detail}")


def build_frames():
    """A PLN benchmark rising 20% while the zloty gains 10% against the dollar."""
    dates = pd.date_range("2026-01-02", periods=6, freq="B")

    wig_pln = pd.Series([100.0, 102.0, 104.0, 108.0, 112.0, 120.0], index=dates)
    spy_usd = pd.Series([500.0, 505.0, 502.0, 510.0, 515.0, 520.0], index=dates)
    urth_usd = pd.Series([150.0, 151.0, 150.5, 152.0, 153.0, 155.0], index=dates)
    plnusd = pd.Series([0.250, 0.252, 0.254, 0.258, 0.262, 0.275], index=dates)

    raw_prices = pd.DataFrame({
        risk.BENCHMARK_WIG: wig_pln,
        risk.BENCHMARK: spy_usd,
        risk.BENCHMARK_MSCI: urth_usd,
    })
    fx = pd.DataFrame({"PLNUSD=X": plnusd})
    return dates, raw_prices, fx, wig_pln, plnusd


def main():
    print("=" * 70)
    print("BENCHMARK CURRENCY")
    print("=" * 70)

    dates, raw_prices, fx, wig_pln, plnusd = build_frames()
    start = dates[0]

    # The benchmark ticker is a real position in main.json, which is the only
    # reason normalisation touches it at all. If that ever stops being true the
    # contamination test below stops testing anything, so assert it.
    config = risk.get_all_position_configs("main")
    check(
        "the WIG benchmark is also a portfolio position",
        risk.BENCHMARK_WIG in config,
        f"{risk.BENCHMARK_WIG} not in main.json — this test no longer covers the bug",
    )
    if risk.BENCHMARK_WIG in config:
        check(
            "and it is held in PLN",
            config[risk.BENCHMARK_WIG]["currency"] == "PLN",
            f"currency is {config[risk.BENCHMARK_WIG]['currency']}",
        )

    usd_prices = risk.normalize_to_base_currency(raw_prices, fx)
    usd_returns = usd_prices.pct_change().dropna(how="all")
    local_returns = raw_prices.pct_change().dropna(how="all")

    pln_truth = wig_pln.iloc[-1] / wig_pln.iloc[0] - 1
    fx_move = plnusd.iloc[-1] / plnusd.iloc[0] - 1
    usd_truth = (1 + pln_truth) * (1 + fx_move) - 1

    # 1. The bug, stated as a fact about the data rather than about the code.
    check(
        "normalisation does move the benchmark column",
        abs(usd_truth - pln_truth) > 0.05,
        f"pln={pln_truth:.4f} usd={usd_truth:.4f}",
    )

    # 2. The fix: with the original-currency frame present, PLN wins.
    series, currency = risk.benchmark_quote_returns(usd_returns, local_returns, risk.BENCHMARK_WIG)
    got = risk._compound_since(series, start)
    check("WIG benchmark is reported in PLN", currency == "PLN", f"got {currency}")
    check(
        "WIG YTD equals the PLN index return",
        got is not None and abs(got - pln_truth) < 1e-12,
        f"got {got}, expected {pln_truth}",
    )
    check(
        "WIG YTD is not the FX-contaminated number",
        got is not None and abs(got - usd_truth) > 0.05,
        f"got {got}, contaminated value is {usd_truth}",
    )

    # 3. A benchmark quoted in the base currency is unaffected either way.
    for ticker in (risk.BENCHMARK, risk.BENCHMARK_MSCI):
        s_local, ccy = risk.benchmark_quote_returns(usd_returns, local_returns, ticker)
        s_none, _ = risk.benchmark_quote_returns(usd_returns, None, ticker)
        a = risk._compound_since(s_local, start)
        b = risk._compound_since(s_none, start)
        truth = raw_prices[ticker].iloc[-1] / raw_prices[ticker].iloc[0] - 1
        check(f"{ticker} stays in USD", ccy == "USD", f"got {ccy}")
        check(
            f"{ticker} return is unchanged by the split",
            a is not None and b is not None and abs(a - b) < 1e-15 and abs(a - truth) < 1e-12,
            f"{a} vs {b} vs {truth}",
        )

    # 4. Without the original frame the number is admitted to be in USD rather
    #    than quietly labelled PLN. A wrong number under an honest label is
    #    recoverable; a wrong number under a clean label is not.
    fallback_series, fallback_ccy = risk.benchmark_quote_returns(usd_returns, None, risk.BENCHMARK_WIG)
    fallback = risk._compound_since(fallback_series, start)
    check("fallback declares USD", fallback_ccy == "USD", f"got {fallback_ccy}")
    check(
        "fallback matches the converted series",
        fallback is not None and abs(fallback - usd_truth) < 1e-12,
        f"got {fallback}, expected {usd_truth}",
    )
    described = risk.describe_benchmark(risk.BENCHMARK_WIG, fallback_ccy)
    check("fallback carries a warning", bool(described.get("warning")), str(described))

    # 5. The description names the series honestly.
    clean = risk.describe_benchmark(risk.BENCHMARK_WIG, "PLN")
    check("clean description carries no warning", "warning" not in clean, str(clean))
    check("description reports the ticker", clean["ticker"] == risk.BENCHMARK_WIG)
    if risk.BENCHMARK_WIG == "ETFBW20TR.WA":
        check(
            "a total-return tracker is not labelled as the price index",
            clean["label"] != "WIG20" and clean["basis"] == "total_return",
            str(clean),
        )
        check("and the label says TR", "TR" in clean["label"], clean["label"])
        check("and the note explains the gap", "price index" in clean.get("note", ""), clean.get("note", ""))

    # 6. A missing benchmark returns None rather than a silent zero at the helper
    #    level — the caller is what turns that into a displayed 0.
    missing_series, _ = risk.benchmark_quote_returns(usd_returns, local_returns, "NOT.A.TICKER")
    check("absent ticker yields no series", missing_series is None)
    check("and compounds to None", risk._compound_since(missing_series, start) is None)

    # 7. Half a window: the YTD slice is inclusive of its start date.
    mid = dates[2]
    partial = risk._compound_since(local_returns[risk.BENCHMARK_WIG], mid)
    expected_partial = wig_pln.iloc[-1] / wig_pln.iloc[1] - 1
    check(
        "compounding from a mid-window date includes that date's return",
        partial is not None and abs(partial - expected_partial) < 1e-12,
        f"got {partial}, expected {expected_partial}",
    )

    # 8. Timezone-aware indexes are handled without mutating the caller's frame.
    tz_returns = local_returns.copy()
    tz_returns.index = tz_returns.index.tz_localize("UTC")
    tz_value = risk._compound_since(tz_returns[risk.BENCHMARK_WIG], start)
    check(
        "tz-aware series compounds to the same number",
        tz_value is not None and abs(tz_value - pln_truth) < 1e-12,
        f"got {tz_value}",
    )
    check(
        "and the source frame keeps its timezone",
        tz_returns.index.tz is not None,
        "the helper mutated its input",
    )

    # 9. NaN padding must not be read as a flat day.
    gappy = local_returns.copy()
    gappy.loc[gappy.index[1], risk.BENCHMARK_WIG] = np.nan
    gap_value = risk._compound_since(gappy[risk.BENCHMARK_WIG], start)
    surviving = local_returns[risk.BENCHMARK_WIG].drop(local_returns.index[1])
    expected_gap = float((1 + surviving).prod() - 1)
    check(
        "a NaN day is dropped, not compounded as zero",
        gap_value is not None and abs(gap_value - expected_gap) < 1e-12,
        f"got {gap_value}, expected {expected_gap}",
    )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All benchmark currency checks passed.")


if __name__ == "__main__":
    main()
