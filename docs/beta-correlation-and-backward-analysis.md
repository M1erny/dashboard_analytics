# Beta, Correlation, And Looking Backwards

Two questions this answers: are beta and correlation right, especially across
rebalances; and will the numbers still be computable years from now, after more
rebalance snapshots have been added.

## Beta and correlation are computed twice, on different books

There are two portfolio return series in `risk.py`, and they mean different
things:

| Series | Built from | Rebalance-aware? |
| --- | --- | --- |
| `portfolio_daily_ret` (risk.py:~1150) | **today's** book's static weights applied to the **full ~5.2 year** download window | **No** |
| `portfolio_val_series` (risk.py:~1502) | `calculate_segmented_ytd`, chained across every dated snapshot | **Yes** |

`Beta`, the headline volatility, Sharpe, Sortino and `Correlation_Matrix` come
from the first. `YTD_Beta`, `YTD_Correlation`, and the YTD vol/Sharpe come from
the second.

The gap is not small. A book that held a beta-1.8 name through one year and
switched to a beta-0.2 name for the next **realised** a two-year beta of about
1.11, while the static replay reports about **0.19** — it describes the book you
hold now, not the book you held.

**What the dashboard displays is the rebalance-aware one.** `ExecutiveSummary`
reads `vitals.ytdBeta`, and every other risk figure a reader sees is built on the
segmented NAV series. The static number is not rendered in the UI. It surfaces in
two places only:

- the CLI report (`python backend/risk.py` prints `Beta:` from the static series)
- as a **fallback** inside `stress_test_portfolio` when the YTD beta is unusable

So the displayed numbers are correct and rebalance-aware. The static series is a
latent second measure that should not be promoted into the UI without a label
saying what it is.

### The stress-test fallback was unreachable, and that was dangerous

`stress_test_portfolio` read `metrics.get('YTD_Beta', metrics['Beta'])`. The
dict-level default can only fire when the *key* is missing, and `YTD_Beta` is
written unconditionally — set to exactly `0.0` on every failure path. So a failed
beta calculation produced a beta of zero, and every scenario printed a market
crash impact of **0.00%**: the most reassuring number the widget can show,
produced by a calculation that did not work.

It now falls through on an unusable value, and every scenario carries
`betaSource`, either `ytd_realised` or `static_current_book`, so a fallback
estimate can be labelled rather than passed off as the realised figure.

### Sign convention on the short book

`short_only_ret` is P&L, not the shorted names' return: it rises when they fall.
An ordinary short book of market-correlated names therefore produces a **negative**
`short_only_beta`, and that negative number is the hedge. The code was right; its
comment said the opposite and has been corrected.

### Known limitations, unchanged by this work

- `ytd_beta_history` uses an **expanding** window anchored at 1 January and never
  re-anchors at a rebalance, so late in a year it describes a blend of books
  rather than the one currently held.
- Its 14-observation minimum is a low bar for an OLS beta; the first plotted point
  is a noisy estimate drawn with the same weight as a settled one.
- `ytd_beta` is derived from the **net** value series while the headline beta uses
  gross returns, so the YTD beta does vary slightly by cost tier.

These are flagged rather than fixed: each changes a displayed number, and that is
a decision for the owner rather than a defect to quietly correct.

## Looking backwards

The ingredients survive by design:

- `LOOKBACK_YEARS = 5.2`, so five years of prices are downloaded every run.
- `main.rebalances.json` preserves every dated snapshot, and `AGENTS.md` forbids
  deleting them.

What did *not* survive was the window. `get_period_params` returns
`f"{datetime.now().year}-01-01"` unconditionally, and every consumer of it is an
open-ended `>= start` filter with the end pinned to the newest price row. There
was no concept of an END anywhere in the engine, so even a backdated start would
have produced "from then until today" rather than "Q2 2026".

`calculate_segmented_ytd`, though, takes its start as a **parameter**. Only
`calculate_risk_metrics` hardcodes it. So a past window needs the contribution
history rebuilt from that year's opening, and nothing about the live YTD path has
to change.

### Asking for a past window

```text
GET /api/book-analytics?period=q2-2026
GET /api/book-analytics?period=2027            # a whole calendar year
GET /api/book-analytics?period=2026-03         # a single month
GET /api/book-analytics?period=custom&start=2026-05-04&end=2026-05-29
```

A period **must name its year** to mean a past one. Bare `q2` always resolves
against the latest year in the data, silently — so `q2` in 2028 means Q2 2028,
never Q2 2026.

For a historical window the rebuild:

- bases the year on the **prior year's final close**, matching what the live YTD
  path does, so a rebuilt year reconciles with what that year reported at the time
- uses `get_effective_portfolio_config(as_of=window end)` — the book that was
  actually live then, never today's
- returns `historical: true` and the `analysisStart` it used
- returns a `warning` when no snapshot exists on or before that year's opening,
  because in that case the opening book was inferred from a later snapshot rather
  than read from the ledger

That warning matters for the owner's stated plan. Adding six more snapshots over
two years is exactly the case this handles well: each new snapshot makes the years
around it *more* reconstructable, because the ledger then records what was held
rather than leaving it to be inferred.

### What is still year-to-date only

The **headline risk metrics** — beta, correlation, volatility, Sharpe, drawdown,
VaR — cannot be windowed to a past year. `calculate_risk_metrics` takes no start
or end parameter and is organised around a single YTD window throughout.

Making those windowed is a restructure of that function rather than an addition
to it, and it is deliberately not attempted here: half-parameterising a 950-line
risk function is how a number ends up computed over one window and labelled with
another.

What works backwards today is exactly what was asked for — hit rate, average
winner versus average loser, profit factor, best and worst contributor, and
concentration — for any window in any year the price history covers.

### The remaining gap

The past-year capability is reachable over HTTP but the **UI only offers the
current year's periods**. A year picker on the Book Analytics strip would close
it; the period labels now keep their year (`Q2 2026` rather than `Q2`) so windows
from different years are distinguishable when it arrives.
