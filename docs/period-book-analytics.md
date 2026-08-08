# Book Analytics Over Time

The Book Analytics strip — batting average, profit factor, win/loss ratio, top-5
gross concentration, best and worst contributor — was year-to-date only. It now
answers "best and worst in Q2" and every other window, without recomputing the
accounting.

## Where the numbers come from

`calculate_segmented_ytd` already builds `position_contribution_history`: a
date × ticker matrix of *cumulative* contribution, chained across every dated
rebalance snapshot and rebased at each seam onto one basis. That single property
is what makes windows possible:

```text
contribution over (a, b]  =  history[b] - history[a]
```

and therefore quarters sum back to the year, exactly. This was verified against
the real function rather than assumed: per-ticker quarter slices reconcile to the
reported YTD contribution to ~1e-16, across rebalance seams, weight changes,
positions that exit, and positions that enter.

The matrix was computed on every request and thrown away. Nothing else changed
about how performance is calculated.

## Three properties that decide what the numbers mean

**Windows are half-open.** `H(b) - H(a)` covers `(a, b]`, so day `a`'s own return
belongs to the previous window. A period must be anchored on the last session
*before* it opens. Anchoring Q2 on 1 April instead of 31 March silently discards
1 April's return — a real error worth 5bp on a synthetic book and unbounded on a
gap day. Every window therefore carries its `anchor` in the payload.

**Contributions are denominated in year-opening capital.** The per-segment
rebasing is exactly what makes windows additive, and it means a Q3 figure reads
"percent of January capital", not "percent return during Q3". The two differ once
the book has moved. The payload states this as `basis`, and the UI labels the
strip `gross`.

**They are gross of financing.** Financing is accounted separately and never
enters a position contribution, so these reconcile to the gross YTD return, never
to the net one.

## Exposure needed new state

Concentration could not be period-aware from what existed: only *current* drifted
weights were kept. But the segment loop already computes `weight * relative_price`
for every position on every date, which is precisely the drifted weight.
`position_weight_history` now captures it.

That addition is a **new output only** — it reads values the loop already
produces and changes no existing calculation. The five accounting suites pass
unchanged, which is the property that mattered.

Exposure is a level rather than a running total, so it is read at the window's
close and never differenced.

## A trap that was live

`contribution_history` was initialised to NaN and closed with `.ffill()`, which
cannot reach *leading* NaNs. A name introduced by a later rebalance therefore had
NaN — not zero — for every date before it entered.

That mattered here. Of the current book, roughly 15 of 36 names were added at the
29 June rebalance. A consumer that subtracts two rows and ranks the result would
have dropped every one of them from any Q1 or Q2 view, and a `nansum` across
quarters could invert a sign: a name that made +4% on the year reading as −6%.

Two defences, because one is not enough for a number nobody would question:

1. `risk.py` now closes the frame with `.ffill().fillna(0.0)`, matching what the
   book-level series alongside it already did. Zero is the correct pre-entry
   cumulative. This is provably inert for existing consumers —
   `calculate_batting_stats` drops exactly-zero cells, so `traded` is unchanged —
   and that was verified by comparing its output row by row before and after.
2. `book_analytics.window_contributions` treats a NaN baseline as zero and drops
   a ticker that never entered, so it stays correct even if the frame ever
   carries NaN again.

## API

Every standard window is precomputed and ships with `/api/metrics`, because each
one is a subtraction on data already in memory:

```json
"bookAnalytics": {
  "basis": "gross_contribution_on_ytd_opening_capital",
  "gross": true,
  "periods": [
    {"key": "q2", "label": "Q2 2026", "start": "2026-04-01", "end": "2026-06-30",
     "anchor": "2026-03-31", "sessions": 63, "metrics": { ... }}
  ]
}
```

Windows offered: `ytd`, `qtd`, `mtd`, `sinceRebalance`, `q1`–`q4`, `h1`/`h2`,
`m1`–`m12`, `r30d`, `r90d`. Only windows the data actually covers are offered, so
the UI never presents a quarter that has not happened.

For anything else:

```text
GET /api/book-analytics?period=custom&start=2026-05-04&end=2026-05-29
```

It reuses the cached market data, so it costs a subtraction rather than a refetch.
It also returns `positions`, ranked by contribution, for the window.

## Reading the strip

The period buttons sit in the strip header; the caption under them gives the
window's exact range, its position count, and that the figures are gross.

The position count changes between periods, and that is correct rather than a
bug: a book rebalanced mid-year genuinely held different names in Q1 and Q3. A
name not held during a window is excluded from the hit-rate denominator entirely,
following `calculate_batting_stats` — a position that was not there is not a loss
it did not have.

A metric with no defined value shows `—` rather than a zero: a window with no
losers has no profit factor, and printing `0.00×` would read as a catastrophe
instead of an absence.

## Tests

`backend/test_book_analytics.py` runs against the real `calculate_segmented_ytd`,
not a re-implementation, and pins:

- quarters summing back to the year, per ticker and in aggregate
- the year reconciling to the reported gross return
- the anchoring off-by-one, by asserting the naive anchor gives a *different*
  answer
- a not-yet-held position never padding the denominator
- a name introduced at a rebalance still ranking in the quarter it earned
- exposure being read at the close, drifting with price, zero when not held,
  negative for shorts
- windows with no losers reporting an undefined profit factor rather than a number
