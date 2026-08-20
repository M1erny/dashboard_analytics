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

    # 4. Without the original-currency frame there is no local reading to show, and
    #    the description must say so rather than presenting the converted number
    #    under a PLN label. A wrong number under an honest label is recoverable; a
    #    wrong number under a clean one is not.
    no_local_base, no_local_local, no_local_desc = risk._benchmark_readings(
        usd_returns, None, fx, risk.BENCHMARK_WIG, start
    )
    check(
        "the base reading still works without the local frame",
        abs(no_local_base - usd_truth) < 1e-12,
        f"got {no_local_base}, expected {usd_truth}",
    )
    check("no local reading is claimed", no_local_local is None, str(no_local_local))
    check("and the gap is stated", bool(no_local_desc.get("warning")), str(no_local_desc))

    # 5. The description names the series honestly.
    clean = risk.describe_benchmark(risk.BENCHMARK_WIG)
    check("a clean description carries no warning", "warning" not in clean, str(clean))
    check("description reports the ticker", clean["ticker"] == risk.BENCHMARK_WIG)
    check("headline currency is the base one", clean["currency"] == "USD", str(clean))
    check("quote currency is kept separately", clean["quoteCurrency"] == "PLN", str(clean))
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

    # 10. The tile subtracts the benchmark from a base-currency portfolio return,
    #     so it needs a base-currency benchmark. Reading the index in PLN is right
    #     for "what did WIG20TR do" and wrong for "did I beat it" — the strip needs
    #     both, and the pp gap must be computed on the comparable one.
    base_series, unavailable = risk.benchmark_base_currency_returns(
        usd_returns, local_returns, fx, risk.BENCHMARK_WIG
    )
    base = risk._compound_since(base_series, start)
    check("a base-currency reading is available", unavailable is None, str(unavailable))
    check(
        "the base reading equals index times FX",
        base is not None and abs(base - usd_truth) < 1e-12,
        f"got {base}, expected {usd_truth}",
    )
    check(
        "and differs from the PLN reading",
        base is not None and abs(base - pln_truth) > 0.05,
        f"base {base} vs local {pln_truth}",
    )

    # A base-currency benchmark is untouched by the conversion.
    for ticker in (risk.BENCHMARK, risk.BENCHMARK_MSCI):
        series, reason = risk.benchmark_base_currency_returns(usd_returns, local_returns, fx, ticker)
        value = risk._compound_since(series, start)
        truth = raw_prices[ticker].iloc[-1] / raw_prices[ticker].iloc[0] - 1
        check(f"{ticker} base reading is unchanged", value is not None and abs(value - truth) < 1e-12, str(value))
        check(f"{ticker} needs no FX", reason is None, str(reason))

    # 11. A PLN benchmark that is NOT a portfolio position is never converted by
    #     normalize_to_base_currency, so the base reading cannot be taken from
    #     whichever frame happens to carry it. Both cases must agree.
    unheld_local = local_returns.rename(columns={risk.BENCHMARK_WIG: "UNHELD.WA"})
    unheld_usd = usd_returns.drop(columns=[risk.BENCHMARK_WIG]).join(unheld_local["UNHELD.WA"])
    original_quote = dict(risk.BENCHMARK_QUOTE_CURRENCY)
    risk.BENCHMARK_QUOTE_CURRENCY["UNHELD.WA"] = "PLN"
    try:
        unheld_series, unheld_reason = risk.benchmark_base_currency_returns(
            unheld_usd, unheld_local, fx, "UNHELD.WA"
        )
        unheld = risk._compound_since(unheld_series, start)
        check(
            "an unheld PLN benchmark is still converted to USD",
            unheld is not None and abs(unheld - usd_truth) < 1e-12,
            f"got {unheld}, expected {usd_truth}; reason {unheld_reason}",
        )
    finally:
        risk.BENCHMARK_QUOTE_CURRENCY.clear()
        risk.BENCHMARK_QUOTE_CURRENCY.update(original_quote)

    # 12. No FX rate means no base reading, rather than a PLN number labelled USD.
    no_fx_series, no_fx_reason = risk.benchmark_base_currency_returns(
        usd_returns, local_returns, raw_prices[[risk.BENCHMARK]], risk.BENCHMARK_WIG
    )
    check("a missing FX rate yields no base reading", no_fx_series is None, str(no_fx_series))
    check("and says which rate is missing", "PLNUSD=X" in (no_fx_reason or ""), str(no_fx_reason))

    # 13. The paired reading carries both numbers and names both currencies.
    base_value, local_value, described_pair = risk._benchmark_readings(
        usd_returns, local_returns, fx, risk.BENCHMARK_WIG, start
    )
    check("the pair reports the base figure first", abs(base_value - usd_truth) < 1e-12, str(base_value))
    check("and the quote-currency figure alongside", abs(local_value - pln_truth) < 1e-12, str(local_value))
    check("headline currency is the base one", described_pair["currency"] == "USD", str(described_pair))
    check("quote currency is named separately", described_pair["localCurrency"] == "PLN", str(described_pair))
    check("no warning on a clean pair", "warning" not in described_pair, str(described_pair))

    # 14. The FX rate must be differenced on the benchmark's own trading days. A
    #     rate that moves while the exchange is shut still belongs to the next
    #     session, and differencing on a calendar grid loses exactly that move.
    #     This is the shape of the real data: FX quotes on days the WSE does not.
    gap_dates = pd.date_range("2026-01-02", periods=6, freq="B")
    gap_local_prices = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=gap_dates)
    # A holiday in the middle of the week: no equity bar, but the zloty keeps moving.
    holiday = gap_dates[3]
    equity_dates = gap_dates.drop(holiday)
    gap_raw = pd.DataFrame({risk.BENCHMARK_WIG: gap_local_prices.reindex(equity_dates)})
    fx_daily = pd.Series(
        [0.250, 0.252, 0.254, 0.230, 0.232, 0.234],  # a 9% drop on the holiday itself
        index=gap_dates,
    )
    gap_fx = pd.DataFrame({"PLNUSD=X": fx_daily})
    gap_local_returns = gap_raw.pct_change().dropna(how="all")
    gap_usd_returns = risk.normalize_to_base_currency(gap_raw, gap_fx).pct_change().dropna(how="all")

    gap_series, gap_reason = risk.benchmark_base_currency_returns(
        gap_usd_returns, gap_local_returns, gap_fx, risk.BENCHMARK_WIG
    )
    gap_value = risk._compound_since(gap_series, equity_dates[0])
    # Truth: the USD price on the first and last equity bars.
    usd_first = gap_local_prices.loc[equity_dates[0]] * fx_daily.loc[equity_dates[0]]
    usd_last = gap_local_prices.loc[equity_dates[-1]] * fx_daily.loc[equity_dates[-1]]
    gap_truth = usd_last / usd_first - 1
    check("a holiday FX move is not lost", gap_reason is None, str(gap_reason))
    check(
        "the base reading matches price times rate across the gap",
        gap_value is not None and abs(gap_value - gap_truth) < 1e-12,
        f"got {gap_value}, expected {gap_truth}",
    )

    # 15. The currency's contribution is reported, so a conversion that silently
    #     stops being applied shows up as a zero instead of hiding.
    _, _, gap_desc = risk._benchmark_readings(
        gap_usd_returns, gap_local_returns, gap_fx, risk.BENCHMARK_WIG, equity_dates[0]
    )
    check("the FX effect is reported", "fxEffect" in gap_desc, str(gap_desc))
    check(
        "and it is not zero when the rate moved",
        abs(gap_desc.get("fxEffect", 0.0)) > 0.01,
        str(gap_desc.get("fxEffect")),
    )

    # 16. A missing FX rate must not print a benchmark of 0.00%. That is the most
    #     reassuring number the tile can show and it would come from a calculation
    #     that did not work. Fall back to the reading that exists, relabel it, and
    #     say the comparison is no longer like-for-like.
    no_fx_base, no_fx_local, no_fx_desc = risk._benchmark_readings(
        usd_returns, local_returns, raw_prices[[risk.BENCHMARK]], risk.BENCHMARK_WIG, start
    )
    check(
        "a missing rate falls back to the PLN reading",
        abs(no_fx_base - pln_truth) < 1e-12,
        f"got {no_fx_base}, expected {pln_truth}",
    )
    check("it is not zero", abs(no_fx_base) > 1e-9, str(no_fx_base))
    check("the local reading is still reported", abs(no_fx_local - pln_truth) < 1e-12, str(no_fx_local))
    check("the tile currency is relabelled", no_fx_desc["currency"] == "PLN", str(no_fx_desc))
    check("no FX effect is claimed", "fxEffect" not in no_fx_desc, str(no_fx_desc))
    check(
        "and the mismatch is stated",
        "not like-for-like" in (no_fx_desc.get("warning") or ""),
        str(no_fx_desc.get("warning")),
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
