# What The Benchmark Tiles Compare Against

The 🇵🇱 tile under the YTD return read noticeably higher than the WIG20 figure on
Google Finance. Two separate reasons, one a defect and one a labelling problem.

## The defect: the index was being multiplied by the zloty

`ETFBW20TR.WA` is unusual in this codebase — it is simultaneously the Polish
benchmark and a **held position** (7.5% short, PLN, in `main.json`).

`normalize_to_base_currency` converts every position into USD, which is exactly
right for portfolio accounting and exactly wrong for a benchmark. The benchmark
path then read its returns out of the same converted frame:

```text
displayed  =  (1 + index move in PLN) × (1 + PLN/USD move) − 1
```

So the tile compounded a Polish index with a currency it is not quoted in. In a
year the zloty moves several percent against the dollar, several percent of pure
FX was printed as index performance. `SPY` and `URTH` escaped only because they
are not positions, so nothing converted them.

The fix does not un-convert anything. `calculate_risk_metrics` now also receives
the **pre-normalisation** price frame — the server already cached it — and
`benchmark_quote_returns` reads a non-USD benchmark from there. The position keeps
its USD series for portfolio maths; the benchmark gets its own PLN series. The two
uses no longer share one column.

If the original-currency frame is ever missing, the old behaviour is what remains
available, so the payload reports `currency: "USD"` and a warning instead of
labelling the number PLN. A wrong number under an honest label can be spotted; a
wrong number under a clean one cannot.

## The labelling problem: TR is not the price index

`ETFBW20TR.WA` is Beta ETF **WIG20TR** — a total-return tracker. It reinvests
dividends and carries fund fees and tracking error. WIG20 as quoted by Google,
Stooq and the press is the **price index**, which pays no dividends.

Those are different series, and the total-return one is structurally higher —
roughly the dividend yield of the index per year, a few points. Displaying it as
`🇵🇱 WIG20` was the dashboard claiming to show something it never had.

Yahoo does not serve the WIG20 price index, so the proxy stays. What changed is
that it now says what it is:

- the tile is labelled from the backend, so it reads `🇵🇱 WIG20TR`
- hovering gives the ticker, the currency, and a sentence explaining that a
  total-return tracker runs above the price index
- `WIG_BENCHMARK_TICKER` overrides the ticker from the environment, so a real
  index feed can be pointed at without a code change

Both benchmark tiles ship a `wigBenchmark` / `msciBenchmark` object in `vitals`
carrying `ticker`, `label`, `basis`, `quoteCurrency`, `currency`, and any warning.

## What is left, and why it is left

The remaining gap against a press quote of WIG20 is the dividend component, and
closing it needs a data source Yahoo does not offer. Substituting a guessed
ticker would be worse than the proxy: an unverifiable symbol that silently
returns nothing becomes a benchmark of `0.00%`, which is a number nobody
questions.

Relative strength in `calculate_momentum_metrics` deliberately still compares a
Polish stock in USD against the benchmark in USD. Both sides carry the same FX
factor there, so the comparison is internally consistent; changing it would move
a displayed number for no gain in correctness.

## The same ticker, two honest numbers

Once the benchmark was read in PLN, `ETFBW20TR.WA` began showing two different
year-to-date figures on one screen:

| Where | Number | Why |
| --- | --- | --- |
| Benchmark tile | +29.0% | the tracker's return **in PLN**, the currency it is quoted in |
| Position row | +24.3% | the same tracker **in USD**, the accounting base currency |

Both are correct and they must differ. A dollar-denominated book holding a zloty
ETF earns the ETF's move plus the zloty's move; the benchmark it is measured
against is quoted in zloty and must not carry that FX component. The gap between
them is exactly the year's PLN/USD move.

`calculate_periodic_returns` runs on the USD frame and always has — that is what
makes a position's return reconcile with its contribution. Nothing there changed.

What was missing was the labelling, and a `title` attribute does not exist on a
phone, which is where this was noticed. So both are now stated on screen:

- the returns column group reads **Returns (USD)**
- a caption under the benchmark strip reads *"WIG20TR: total return in PLN, above
  the WIG20 price index. SPY and MSCI in USD."*

That caption also settles the other half of the confusion. The press quotes WIG20,
the price index; the tile tracks WIG20**TR**, which adds dividends. At a price
index around +24% the total-return series sits near +29%, and the coincidence that
the ETF's *USD* return is also near +24% makes the price index and the currency
effect easy to mistake for each other. They are two separate gaps that happened to
be the same size.

## Tests

`backend/test_benchmark_currency.py` pins:

- the WIG YTD equalling the PLN index return, and **differing** from the
  FX-converted one, so the bug cannot come back unnoticed
- USD benchmarks producing an identical number through either frame
- the fallback path declaring USD and carrying a warning
- a total-return tracker never being described with the price index's label
- half-window compounding including the start date's return
- tz-aware indexes compounding identically without mutating the caller's frame
- a NaN session being dropped rather than compounded as a flat day
- `ETFBW20TR.WA` still being a PLN position in `main.json` — if it stops being
  one, the contamination test stops testing anything, and it should fail loudly
