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

## A benchmark needs two readings, not one

Reading the benchmark in PLN fixed one thing and broke another. The tile does not
just display a number — it prints a difference against the portfolio, and it sits
beside two USD benchmarks. Subtracting a PLN return from a USD portfolio return is
not arithmetic, and comparing a PLN tile against a USD tile beside it is not a
comparison. The strip had three values on two different axes.

The two readings answer different questions and the strip needs both:

| Reading | Answers | Where it shows |
| --- | --- | --- |
| Base currency (USD) | what would holding it have done for this book? | the headline figure and the pp gap |
| Quote currency (PLN) | what did the index itself do? | the small line beneath |

So `ETFBW20TR.WA` now reads **+24.3%** with **PLN +29.0%** under it, and the pp gap
against the portfolio finally means something. Both numbers are true; only one of
them can be subtracted.

`benchmark_base_currency_returns` applies the conversion explicitly rather than
reading whichever frame happens to carry the ticker. That distinction is not
cosmetic: a benchmark that is also a position arrives already converted in the USD
frame, while one that is not stays in its own currency there, and nothing in the
frame says which. A test covers the unheld case, because the current ticker is held
and would hide the bug.

`describe_benchmark` therefore reports `currency` (always the base currency, the one
the headline is in) separately from `quoteCurrency` and `localCurrency`. When the
original-currency frame is missing there is no local reading to show, and the
description says so instead of presenting the converted number under a PLN label.

## The position row is a third number, and also right

The same ticker's YTD in the positions table is **+24.3%** — the same base-currency
figure, because `calculate_periodic_returns` runs on the USD frame and always has.
That is what makes a position's return reconcile with its contribution.

The labelling makes all of it legible: the returns column group reads **Returns
(USD)**, and a caption under the benchmark strip states that all three benchmarks
are shown in the base currency so the pp gaps compare, that WIG20TR is a
total-return tracker, and that its PLN reading is the line beneath it.

That caption also settles the other half of the confusion. The press quotes WIG20,
the price index; the tile tracks WIG20**TR**, which adds dividends. At a price index
around +24% the total-return series sits near +29%, and the coincidence that the
ETF's *USD* return is also near +24% makes the price index and the currency effect
easy to mistake for each other. They are two separate gaps that happened to be the
same size.

## Two things that would have hidden

**The rate has to be differenced on the benchmark's own trading days.** Differencing
it on a calendar grid and then sampling the trading days measures each day's move
from the previous *calendar* row, not the previous *trading* row — so anything the
currency did while the exchange was shut is dropped. Polish holidays are not many,
but they are exactly the days a currency moves without an equity bar to attach it
to. The alignment also needs one row of run-up: a return series' first row
describes a move out of a session that is no longer in the index, and without the
last rate before it that session's currency move disappears. Both are pinned by a
test with a holiday in the middle of the week and a 9% rate move on it.

**A missing FX rate must not print 0.00%.** That is the most reassuring number the
tile can show, produced by a calculation that did not work — the same failure this
codebase already fixed once for the stress-test beta. The reading that does exist
is shown instead, relabelled with its actual currency, and the description says the
gap against the portfolio is no longer like-for-like.

The caption states the currency's own contribution — `FX -4.7pp` — rather than
leaving it to be inferred from two rounded percentages on screen. It is there to be
read as a check: if it ever says `0pp` while the zloty has moved, the conversion has
stopped being applied.

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
