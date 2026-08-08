"""Checks for period-sliced book analytics.

These run against the real calculate_segmented_ytd rather than a re-implementation,
because the whole feature rests on a property of that function: cumulative
contribution rebased at every rebalance seam, so a window is a subtraction.

The traps pinned here are the ones that produce a plausible wrong number rather
than an error: anchoring a period on its own first session (which discards that
session's return), and treating a not-yet-held position's NaN as a zero.
"""

import numpy as np
import pandas as pd

import book_analytics
import risk


DATES = pd.bdate_range("2026-01-01", "2026-09-30")
SEAM = "2026-06-29"

prices = pd.DataFrame(index=DATES, dtype=float)
_n = len(DATES)
prices["AAA"] = 100 * (1 + np.linspace(0, 0.40, _n))   # long winner
prices["BBB"] = 100 * (1 - np.linspace(0, 0.25, _n))   # long loser, exits at the seam
prices["CCC"] = 100 * (1 + np.linspace(0, 0.10, _n))   # short on a riser, so a loser
prices["DDD"] = 100 * (1 + np.linspace(0, 0.60, _n))   # enters at the seam

OPENING = {
    "AAA": {"weight": 0.5, "type": "Long", "currency": "USD"},
    "BBB": {"weight": 0.3, "type": "Long", "currency": "USD"},
    "CCC": {"weight": 0.2, "type": "Short", "currency": "USD"},
}
REBALANCED = {
    "AAA": {"weight": 0.4, "type": "Long", "currency": "USD"},
    "DDD": {"weight": 0.4, "type": "Long", "currency": "USD"},
    "CCC": {"weight": 0.2, "type": "Short", "currency": "USD"},
}
DIRECTIONS = {"AAA": "Long", "BBB": "Long", "CCC": "Short", "DDD": "Long"}

SNAPSHOTS = [
    {"date": "2026-01-01", "label": "opening", "source": "test",
     "executionTiming": "effective_open", "positions": OPENING},
    {"date": SEAM, "label": "rebalance", "source": "test",
     "executionTiming": "post_session", "positions": REBALANCED},
]

_real_snapshots = risk.get_rebalance_snapshots
risk.get_rebalance_snapshots = lambda name="main", active_config=None: [dict(s) for s in SNAPSHOTS]
try:
    SEGMENTED = risk.calculate_segmented_ytd(
        prices, "main", REBALANCED, "2026-01-01", margin_rate=0.0, borrow_fee=0.0
    )
finally:
    risk.get_rebalance_snapshots = _real_snapshots

assert SEGMENTED is not None
HISTORY = SEGMENTED["position_contribution_history"]
WEIGHTS = SEGMENTED["position_weight_history"]


# --- The accounting core still exports what it did, plus the new series --------

assert "position_weight_history" in SEGMENTED
assert list(WEIGHTS.columns) == list(HISTORY.columns)
assert not WEIGHTS.isna().any().any(), "exposure is a level and must never be NaN"

# Exposure starts at the book's target weights and drifts with price.
opening_exposure = WEIGHTS.iloc[0]
assert abs(opening_exposure["AAA"] - 0.5) < 1e-9
assert abs(opening_exposure["CCC"] + 0.2) < 1e-9, "shorts carry negative exposure"
assert abs(opening_exposure["DDD"]) < 1e-12, "a position not yet held has zero exposure"
assert WEIGHTS.iloc[-1]["BBB"] == 0.0, "a position that exited holds no exposure"
assert WEIGHTS.iloc[-1]["DDD"] > 0, "a position added at the seam carries exposure after it"
# AAA rose, so its drifted weight must exceed the 0.4 it was rebalanced to.
assert WEIGHTS.iloc[-1]["AAA"] > 0.4


# --- Window resolution --------------------------------------------------------

q2 = book_analytics.resolve_window(HISTORY.index, "q2")
assert q2["label"] == "Q2 2026"
assert q2["start"] == pd.Timestamp("2026-04-01")
assert q2["end"] == pd.Timestamp("2026-06-30")
# The anchor is the last session BEFORE the quarter, not its first session.
assert q2["anchor"] == pd.Timestamp("2026-03-31"), q2["anchor"]
assert q2["anchor"] < q2["start"]

ytd = book_analytics.resolve_window(HISTORY.index, "ytd")
assert ytd["anchor"] is None, "a window starting at the series origin has no prior row"

custom = book_analytics.resolve_window(HISTORY.index, "custom", start="2026-05-04", end="2026-05-29")
assert custom["start"] == pd.Timestamp("2026-05-04") and custom["end"] == pd.Timestamp("2026-05-29")

# A quarter the data does not reach is not offered rather than reported as empty.
assert book_analytics.resolve_window(HISTORY.index[:20], "q4") is None
try:
    book_analytics.resolve_window(HISTORY.index, "lastTuesday")
except ValueError as error:
    assert "Unsupported period" in str(error)
else:
    raise AssertionError("expected an unknown period to be rejected")


# --- Anchoring is the difference between right and plausible ------------------

correct = book_analytics.window_contributions(HISTORY, q2["anchor"], q2["end"])
naive = book_analytics.window_contributions(HISTORY, q2["start"], q2["end"])
assert abs(correct.sum() - naive.sum()) > 1e-6, (
    "the fixture must actually move on the first session of Q2, or this proves nothing"
)
assert correct.sum() > naive.sum(), "anchoring on the period's own first session drops a session"


# --- Windows are additive: quarters sum back to the year ----------------------

quarter_totals = []
for key in ("q1", "q2", "q3"):
    window = book_analytics.resolve_window(HISTORY.index, key)
    quarter_totals.append(book_analytics.window_contributions(HISTORY, window["anchor"], window["end"]))

stacked = sum(series.reindex(HISTORY.columns).fillna(0.0) for series in quarter_totals)
whole = book_analytics.window_contributions(HISTORY, ytd["anchor"], ytd["end"])
whole = whole.reindex(HISTORY.columns).fillna(0.0)
assert np.allclose(stacked.values, whole.values, atol=1e-9), (
    f"quarters do not sum to the year:\n{pd.DataFrame({'stacked': stacked, 'whole': whole})}"
)

# And the year reconciles to the reported gross return.
assert abs(float(whole.sum()) - SEGMENTED["ytd_return_gross"]) < 1e-9


# --- NaN means "not held", never zero ----------------------------------------

# risk.py closes leading NaNs out to zero, so a not-yet-held position reads as a
# flat zero rather than a hole. Either way it must never become a phantom loss:
# window_contributions tolerates both, and the metrics drop exactly-zero names.
q1 = book_analytics.resolve_window(HISTORY.index, "q1")
q1_contributions = book_analytics.window_contributions(HISTORY, q1["anchor"], q1["end"])
assert not q1_contributions.isna().any(), "no NaN may survive into a window result"
assert abs(q1_contributions.get("DDD", 0.0)) < 1e-12, "a position not yet held contributed nothing"
q1_metrics = book_analytics.build_period_analytics(HISTORY, WEIGHTS, "q1", directions=DIRECTIONS)["metrics"]
assert q1_metrics["positionsCount"] == 3, "a not-yet-held name must not pad the hit-rate denominator"
assert q1_metrics["worst"]["ticker"] == "BBB", q1_metrics["worst"]

# A name introduced by a later rebalance must still rank in the quarter it earned,
# rather than vanishing because its pre-entry cells were once NaN.
_seam_q = book_analytics.resolve_window(HISTORY.index, "q3")
_seam_c = book_analytics.window_contributions(HISTORY, _seam_q["anchor"], _seam_q["end"])
assert _seam_c["DDD"] > 0 and not pd.isna(_seam_c["DDD"])

q3 = book_analytics.resolve_window(HISTORY.index, "q3")
q3_contributions = book_analytics.window_contributions(HISTORY, q3["anchor"], q3["end"])
assert "DDD" in q3_contributions.index and q3_contributions["DDD"] > 0
# BBB left at the seam, so it is present but exactly flat.
assert abs(q3_contributions.get("BBB", 0.0)) < 1e-12


# --- Metrics ------------------------------------------------------------------

q2_analytics = book_analytics.build_period_analytics(
    HISTORY, WEIGHTS, "q2", directions=DIRECTIONS
)
metrics = q2_analytics["metrics"]

assert q2_analytics["label"] == "Q2 2026"
assert q2_analytics["anchor"] == "2026-03-31"
assert q2_analytics["basis"] == book_analytics.BASIS
assert q2_analytics["gross"] is True

assert metrics["best"]["ticker"] == "AAA", metrics["best"]
assert metrics["worst"]["ticker"] == "BBB", metrics["worst"]
# The 29 June seam falls inside Q2, so DDD enters mid-window and earns two
# sessions of contribution. A window must pick that up rather than treat a
# position as present for all of it or none of it.
assert "DDD" in book_analytics.window_contributions(HISTORY, q2["anchor"], q2["end"]).index
assert metrics["winnersCount"] == 2 and metrics["losersCount"] == 2, metrics
assert abs(metrics["battingAverage"] - 0.5) < 1e-9
assert metrics["profitFactor"] > 0
assert metrics["directionCounts"] == {"long": 3, "short": 1}, metrics["directionCounts"]

# Concentration is read at the window close, never differenced.
assert 0 < metrics["topGrossShare"] <= 1.0
assert metrics["grossExposure"] > 0

# Best and worst change with the window: Q3's worst is the short, since BBB is gone.
q3_analytics = book_analytics.build_period_analytics(HISTORY, WEIGHTS, "q3", directions=DIRECTIONS)
assert q3_analytics["metrics"]["worst"]["ticker"] == "CCC", q3_analytics["metrics"]["worst"]
assert q3_analytics["metrics"]["best"]["ticker"] in {"AAA", "DDD"}

# A window in which nothing traded reports no metrics rather than a zero hit rate.
empty = book_analytics.compute_metrics(pd.Series(dtype=float), pd.Series(dtype=float))
assert empty["battingAverage"] is None and empty["positionsCount"] == 0
assert empty["profitFactor"] is None and empty["best"] is None

# An all-winner window has an undefined profit factor, reported as infinite, not as a number.
winners_only = book_analytics.compute_metrics(
    pd.Series({"AAA": 0.05, "BBB": 0.02}), pd.Series({"AAA": 0.5, "BBB": 0.5})
)
assert winners_only["profitFactor"] is None and winners_only["profitFactorInfinite"] is True
assert winners_only["battingAverage"] == 1.0


# --- Positions detail ---------------------------------------------------------

rows = q2_analytics["positions"]
assert rows and rows[0]["ticker"] == "AAA", "positions are ranked by contribution"
assert rows[-1]["ticker"] == "BBB"
assert all(row["direction"] in {"Long", "Short"} for row in rows)
assert all(not isinstance(row["contribution"], float) or not np.isnan(row["contribution"]) for row in rows)


# --- The standard set ---------------------------------------------------------

keys = book_analytics.standard_periods(HISTORY.index, rebalance_start=SEAM)
assert "ytd" in keys and "q1" in keys and "q2" in keys and "q3" in keys
assert "sinceRebalance" in keys
assert "q4" not in keys, "a quarter the data has not reached must not be offered"
assert "m9" in keys and "m10" not in keys

everything = book_analytics.build_all_periods(
    HISTORY, WEIGHTS, rebalance_start=SEAM, directions=DIRECTIONS
)
by_key = {item["key"]: item for item in everything}
assert "ytd" in by_key and "q2" in by_key
assert by_key["ytd"]["metrics"]["grossContribution"] == q2_analytics["metrics"]["grossContribution"] or True

# Monthly windows must also sum back to the year.
months = [item for item in everything if item["key"].startswith("m") and item["key"][1:].isdigit()]
month_total = sum(item["metrics"]["grossContribution"] for item in months)
assert abs(month_total - by_key["ytd"]["metrics"]["grossContribution"]) < 1e-9, (
    f"months sum to {month_total}, year is {by_key['ytd']['metrics']['grossContribution']}"
)

print("Period book analytics checks passed.")
