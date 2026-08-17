# Where This Codebase Should Go Next

A review of the whole dashboard, written after building the self-build agent, the
Drive ingestion work, and period-aware book analytics. Ordered by what actually
blocks future work rather than by what is easiest to describe.

## What is already right, and worth protecting

**The rebalance ledger is the best decision in this project.** `main.rebalances.json`
plus the rules in `AGENTS.md` are why any backward analysis is possible at all.
The contribution matrix chains across every seam and reconciles to ~1e-16 — that
was measured, not assumed. Most portfolio tools cannot answer "what did I hold in
Q2 two years ago" because they overwrite. This one cannot overwrite, by rule.

**The code is unusually honest about its own numbers.** `Current_Book_Scenario`
carries `scope: "Static current-target-weight replay; not realised portfolio
history"`. `calculate_batting_stats` excludes names that have had no return day
rather than counting them as losses. Gross and net are separated throughout.
Someone thought carefully here, and that instinct is worth keeping.

**CI now exists.** Types, lint, build and sixteen backend suites run on every pull
request. That is the gate that makes machine-written code reviewable.

## The five things that will slow everything down

### 1. Two functions hold most of the logic

```text
risk.py     calculate_risk_metrics    961 lines
server.py   get_metrics               764 lines
```

Every future change lands in one of them. `calculate_risk_metrics` is built
around a single year-to-date window with no start or end parameter, which is
exactly why headline beta, correlation, volatility and drawdown cannot be asked
about a past quarter while the book analytics can.

**Do not rewrite either one.** Extract one metric at a time into a function with
explicit `(series, start, end)` parameters, and pair each extraction with a test
that asserts the new path reproduces the old number exactly. The
`position_weight_history` change is the pattern: a new output that reads values
the loop already produced, changing no existing calculation, verified by the
existing suites passing untouched.

Order that pays off soonest: volatility and drawdown first (self-contained), beta
and correlation next (they need a benchmark alignment helper), VaR/CVaR last.

### 2. The backend/frontend contract is retyped by hand

`fetchDashboardData` rebuilds the report from an explicit list of keys. Anything
not on that list is silently dropped — which is how `bookAnalytics` reached the
browser as `undefined` while TypeScript compiled cleanly and the UI rendered a
plausible fallback.

That is a *class* of bug, not an incident. Two fixes, either acceptable:

- generate types from FastAPI's OpenAPI schema, or
- spread the response (`...data`) and override only the fields that need
  reshaping, instead of allow-listing

Then add one contract test asserting every top-level key of `/api/metrics`
survives into `FullRiskReport`. It would have caught this in seconds.

### 3. Tests are assertion scripts, not a suite

Sixteen files, each run separately, each stopping at its first failed assertion.
Moving to pytest is not cosmetic:

- you see every failure in a run instead of the first one
- `@parametrize` lets the same accounting assertions run across many books and
  windows, which is precisely what this domain needs
- CI reports which case failed rather than which file

The existing files convert almost mechanically: they are already flat assertions.

### 4. Twelve one-off scripts sit in `backend/`

`debug_msft.py`, `debug_pln.py`, `analyze_extremes.py`, `compare_beta.py` and
eight more. They were useful once. Now they dilute the directory and — newly
relevant — they enter the pool of files the self-build agent scores when choosing
context. Move them to `backend/scratch/` or delete them. This is a ten-minute
job with a real payoff.

### 5. The cache is a dict in one process

`_cache` and `_data_cache` live in memory with a 300-second TTL. Every Render
restart is a cold start, and a cold start against yfinance is what makes the
dashboard occasionally hang until the frontend's 90-second timeout. For a single
user this is tolerable; it is also the single most likely reason the app feels
slow. A small persistent cache (SQLite on disk, or Supabase) would remove the
cliff.

## Payload shape

`/api/metrics` now carries vitals, positions, two history series, analytics
history, stress tests, and book analytics for every standard window. It grew
again in this session because adding to it was the cheapest option each time.

Split it: a fast endpoint for the tiles and a second for the chart series. The
tiles are what you look at first and they depend on the least data. Right now
nothing renders until everything is computed.

## Specific unfinished items

| Item | Where | Effort |
| --- | --- | --- |
| Year picker for backward windows | `ReturnsHeatmap.tsx` — API already supports `q2-2026` | small |
| Beta expanding window never re-anchors at a rebalance | `risk.py` `ytd_beta_history` | medium, changes a displayed number |
| 14-observation minimum is a low bar for an OLS beta | same | small, changes a displayed number |
| YTD beta varies by cost tier (net series) while headline uses gross | `risk.py` | small, decide which is intended |
| OCR for scanned PDFs | ingestion | large, needs a dependency |
| `.doc` / `.xls` / `.ppt` extractors | `office_extract.py` | medium, needs a dependency |

The three beta items are deliberately left as decisions rather than defects: each
one moves a number on screen, and that is the owner's call.

## About the self-build agent

The technical risk is contained: an allowlist, CI, and a human merge. The real
risk is behavioural — merging without reading the diff because the first ten
proposals looked fine.

Two suggestions:

**Read ten diffs before enabling `BRAIN_CODE_ALLOW_MERGE`.** Not as ceremony. You
will learn where this particular model is confidently wrong, and that knowledge
is what makes the merge button safe later.

**Smaller files make the agent better, measurably.** It selects roughly eight
files as context. With `server.py` at 5,410 lines and `risk.py` at 2,665, it can
only ever see a fraction, and it edits by anchor because a full rewrite would be
unsafe. Every extraction from those two files widens what the agent can actually
reason about. This is the practical argument for refactoring, and it is stronger
than the aesthetic one.

## Suggested order

0. **Turn on what already exists** — GitHub token, forced Drive re-sync, embed,
   then measure coverage. Several features are merged but inert until this.
1. **Move the debug scripts.** Ten minutes.
2. **pytest, plus the contract test.** Half a day, and the best ratio of payoff
   to risk on this list.
3. **Split the metrics payload** into tiles and history.
4. **Extract risk metrics one at a time**, each with a before/after equality test.
   This is what eventually unlocks "beta for Q2 2027".

Steps 1–3 are low risk and make step 4 tractable. Step 4 is where the analytical
value is, and it is the one that must not be rushed: on a portfolio dashboard, a
number computed over one window and labelled with another is worse than no number
at all.
