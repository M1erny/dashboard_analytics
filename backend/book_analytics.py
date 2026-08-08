"""Book analytics over arbitrary time windows.

The dashboard's Book Analytics strip (batting average, profit factor, win/loss
ratio, top-5 gross concentration, best and worst contributor) was year-to-date
only. This computes the same six metrics for any window.

It rests on one property of `calculate_segmented_ytd`: `position_contribution_history`
is CUMULATIVE from the YTD start and rebased onto a single basis at every rebalance
seam, so a window's contribution is a subtraction. Quarters therefore sum back to
the year exactly.

Three things about that basis decide whether the numbers mean what they look like:

1. The difference H(b) - H(a) covers the half-open window (a, b]. Day a's own
   return belongs to the previous window. A period must therefore be anchored on
   the last session BEFORE it starts, not on its own first session — anchoring Q2
   on 1 April silently discards 1 April's return.

2. Contributions are scaled by the portfolio value at each segment's start, which
   denominates every window in YTD-OPENING capital. That is exactly what makes
   windows additive, and it means a Q3 figure is "percent of January capital", not
   "percent return during Q3". The two differ once the book has moved.

3. The series is GROSS of financing. Financing is accounted separately and never
   appears in position contributions, so these figures reconcile to the gross YTD
   return, never to the net one.

Every one of those is surfaced in the payload rather than left for the reader to
discover.
"""

import calendar
from typing import Any

import numpy as np
import pandas as pd


BASIS = "gross_contribution_on_ytd_opening_capital"

QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}


def _as_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        raise ValueError(f"Could not read {value!r} as a date. Use YYYY-MM-DD.")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_localize(None)
    return stamp.normalize()


def _last_row_on_or_before(index: pd.DatetimeIndex, stamp: pd.Timestamp) -> pd.Timestamp | None:
    eligible = index[index <= stamp]
    return eligible[-1] if len(eligible) else None


def _first_row_on_or_after(index: pd.DatetimeIndex, stamp: pd.Timestamp) -> pd.Timestamp | None:
    eligible = index[index >= stamp]
    return eligible[0] if len(eligible) else None


def resolve_window(
    index: pd.DatetimeIndex,
    period: str,
    *,
    start: Any = None,
    end: Any = None,
    rebalance_start: Any = None,
) -> dict[str, Any] | None:
    """Turn a period key into (anchor, end) rows of the price index.

    `anchor` is the last session strictly before the period, because the
    difference of two cumulative values covers the half-open window (anchor, end].
    A period that begins at the very start of the series has no anchor row, and the
    caller treats that as a zero baseline.
    """
    if index is None or len(index) == 0:
        return None

    index = pd.DatetimeIndex(index)
    first, last = index[0], index[-1]
    year = int(last.year)
    key = (period or "ytd").strip().lower()

    if key == "custom":
        window_start = _as_timestamp(start) or first
        window_end = _as_timestamp(end) or last
        label = f"{window_start.date()} to {window_end.date()}"
    elif key == "ytd":
        window_start, window_end, label = first, last, "Year to date"
    elif key == "qtd":
        quarter = (last.month - 1) // 3 + 1
        month_from, _ = QUARTER_MONTHS[quarter]
        window_start = pd.Timestamp(year=year, month=month_from, day=1)
        window_end, label = last, f"Q{quarter} to date"
    elif key == "mtd":
        window_start = pd.Timestamp(year=year, month=last.month, day=1)
        window_end, label = last, f"{last.strftime('%B')} to date"
    elif key in {"q1", "q2", "q3", "q4"}:
        quarter = int(key[1])
        month_from, month_to = QUARTER_MONTHS[quarter]
        window_start = pd.Timestamp(year=year, month=month_from, day=1)
        window_end = pd.Timestamp(
            year=year, month=month_to, day=calendar.monthrange(year, month_to)[1]
        )
        label = f"Q{quarter} {year}"
    elif key in {"h1", "h2"}:
        month_from, month_to = (1, 6) if key == "h1" else (7, 12)
        window_start = pd.Timestamp(year=year, month=month_from, day=1)
        window_end = pd.Timestamp(
            year=year, month=month_to, day=calendar.monthrange(year, month_to)[1]
        )
        label = f"{key.upper()} {year}"
    elif key.startswith("m") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        month = int(key[1:])
        window_start = pd.Timestamp(year=year, month=month, day=1)
        window_end = pd.Timestamp(year=year, month=month, day=calendar.monthrange(year, month)[1])
        label = f"{window_start.strftime('%B %Y')}"
    elif key in {"r30d", "r90d", "r180d"}:
        days = int(key[1:-1])
        window_start = last - pd.Timedelta(days=days)
        window_end, label = last, f"Last {days} days"
    elif key == "sincerebalance":
        anchor_stamp = _as_timestamp(rebalance_start)
        if anchor_stamp is None:
            return None
        window_start, window_end, label = anchor_stamp, last, "Since rebalance"
    else:
        raise ValueError(f"Unsupported period: {period}")

    window_start = max(window_start, first)
    window_end = min(window_end, last)
    if window_end < window_start:
        return None

    end_row = _last_row_on_or_before(index, window_end)
    start_row = _first_row_on_or_after(index, window_start)
    if end_row is None or start_row is None or end_row < start_row:
        return None

    # The session before the window opens. Its absence means the window starts at
    # the series origin, where cumulative contribution is zero by construction.
    earlier = index[index < start_row]
    anchor_row = earlier[-1] if len(earlier) else None

    return {
        "key": key,
        "label": label,
        "anchor": anchor_row,
        "start": start_row,
        "end": end_row,
        "sessions": int(((index >= start_row) & (index <= end_row)).sum()),
    }


def window_contributions(
    contribution_history: pd.DataFrame,
    anchor: pd.Timestamp | None,
    end: pd.Timestamp,
) -> pd.Series:
    """Per-ticker contribution over (anchor, end], as a subtraction.

    A ticker that had not entered the book by `anchor` is NaN there, which is not
    the same as zero: NaN means "not held", and subtracting it would poison every
    aggregate. Its baseline is zero, and a ticker still NaN at `end` never entered
    the window at all and is dropped.
    """
    if contribution_history is None or contribution_history.empty:
        return pd.Series(dtype=float)

    end_values = contribution_history.loc[end]
    if anchor is None:
        base = pd.Series(0.0, index=contribution_history.columns)
    else:
        base = contribution_history.loc[anchor].fillna(0.0)

    held = end_values.notna()
    return (end_values[held] - base[held]).astype(float)


def window_weights(
    weight_history: pd.DataFrame | None,
    end: pd.Timestamp,
) -> pd.Series:
    """Signed drifted exposure at the window's close.

    Exposure is a level rather than a running total, so it is read at a date and
    never differenced.
    """
    if weight_history is None or weight_history.empty or end not in weight_history.index:
        return pd.Series(dtype=float)
    return weight_history.loc[end].astype(float)


def compute_metrics(
    contributions: pd.Series,
    weights: pd.Series,
    *,
    directions: dict[str, str] | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    """The six Book Analytics metrics for one window.

    Positions with exactly zero contribution are excluded from the hit-rate
    denominator, matching calculate_batting_stats in risk.py: a name that was in
    the book but had no return day in the window is not a loss it has not had.
    """
    clean = contributions.dropna()
    traded = clean[clean != 0.0]

    winners = traded[traded > 0]
    losers = traded[traded < 0]
    total_gains = float(winners.sum())
    total_losses = float(abs(losers.sum()))

    batting = float(len(winners) / len(traded)) if len(traded) else None

    if total_losses > 0:
        profit_factor: float | None = total_gains / total_losses
    elif total_gains > 0:
        profit_factor = float("inf")
    else:
        profit_factor = None

    average_win = total_gains / len(winners) if len(winners) else 0.0
    average_loss = total_losses / len(losers) if len(losers) else 0.0
    if average_loss > 0:
        win_loss: float | None = average_win / average_loss
    elif average_win > 0:
        win_loss = float("inf")
    else:
        win_loss = None

    best_ticker = str(traded.idxmax()) if len(traded) else None
    worst_ticker = str(traded.idxmin()) if len(traded) else None

    exposure = weights.dropna().abs()
    exposure = exposure[exposure > 0]
    gross_exposure = float(exposure.sum())
    top_exposure = float(exposure.nlargest(top_n).sum()) if len(exposure) else 0.0
    top_share = (top_exposure / gross_exposure) if gross_exposure > 0 else None

    return {
        "battingAverage": batting,
        "winnersCount": int(len(winners)),
        "losersCount": int(len(losers)),
        "positionsCount": int(len(traded)),
        "profitFactor": _finite(profit_factor),
        "profitFactorInfinite": profit_factor == float("inf"),
        "winLossRatio": _finite(win_loss),
        "winLossRatioInfinite": win_loss == float("inf"),
        "averageWin": average_win or None,
        "averageLoss": average_loss or None,
        "grossContribution": float(clean.sum()) if len(clean) else 0.0,
        "totalGains": total_gains,
        "totalLosses": total_losses,
        "best": {"ticker": best_ticker, "contribution": float(traded.max())} if best_ticker else None,
        "worst": {"ticker": worst_ticker, "contribution": float(traded.min())} if worst_ticker else None,
        "topGrossWeight": top_exposure or None,
        "topGrossShare": top_share,
        "grossExposure": gross_exposure or None,
        "topN": top_n,
        "directionCounts": _direction_counts(traded.index, directions),
    }


def _direction_counts(tickers, directions: dict[str, str] | None) -> dict[str, int]:
    if not directions:
        return {}
    counts = {"long": 0, "short": 0}
    for ticker in tickers:
        side = str(directions.get(ticker, "")).strip().lower()
        if side == "long":
            counts["long"] += 1
        elif side == "short":
            counts["short"] += 1
    return counts


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (np.isinf(value) or np.isnan(value)):
        return None
    return float(value)


def build_period_analytics(
    contribution_history: pd.DataFrame,
    weight_history: pd.DataFrame | None,
    period: str,
    *,
    start: Any = None,
    end: Any = None,
    rebalance_start: Any = None,
    directions: dict[str, str] | None = None,
    top_n: int = 5,
    include_positions: bool = True,
) -> dict[str, Any] | None:
    """Metrics plus per-position detail for one window."""
    if contribution_history is None or contribution_history.empty:
        return None

    window = resolve_window(
        contribution_history.index,
        period,
        start=start,
        end=end,
        rebalance_start=rebalance_start,
    )
    if window is None:
        return None

    contributions = window_contributions(contribution_history, window["anchor"], window["end"])
    weights = window_weights(weight_history, window["end"])
    metrics = compute_metrics(contributions, weights, directions=directions, top_n=top_n)

    payload: dict[str, Any] = {
        "key": window["key"],
        "label": window["label"],
        "start": window["start"].strftime("%Y-%m-%d"),
        "end": window["end"].strftime("%Y-%m-%d"),
        "anchor": window["anchor"].strftime("%Y-%m-%d") if window["anchor"] is not None else None,
        "sessions": window["sessions"],
        "basis": BASIS,
        "gross": True,
        "metrics": metrics,
    }

    if include_positions:
        rows = []
        for ticker, value in contributions.sort_values(ascending=False).items():
            if pd.isna(value):
                continue
            weight = weights.get(ticker)
            rows.append(
                {
                    "ticker": str(ticker),
                    "contribution": float(value),
                    "weight": float(weight) if weight is not None and not pd.isna(weight) else None,
                    "direction": (directions or {}).get(str(ticker)),
                }
            )
        payload["positions"] = rows

    return payload


def standard_periods(index: pd.DatetimeIndex, *, rebalance_start: Any = None) -> list[str]:
    """Period keys worth precomputing, in the order a reader would want them.

    Only periods the data actually covers are offered, so the UI never presents a
    quarter that has not happened.
    """
    if index is None or len(index) == 0:
        return []

    index = pd.DatetimeIndex(index)
    last = index[-1]
    keys = ["ytd", "qtd", "mtd"]
    if rebalance_start:
        keys.append("sinceRebalance")

    current_quarter = (last.month - 1) // 3 + 1
    for quarter in range(1, current_quarter + 1):
        month_from, _ = QUARTER_MONTHS[quarter]
        if pd.Timestamp(year=int(last.year), month=month_from, day=1) >= index[0] or quarter == 1:
            keys.append(f"q{quarter}")
    if current_quarter >= 3:
        keys.append("h1")

    for month in range(1, last.month + 1):
        keys.append(f"m{month}")

    keys.extend(["r30d", "r90d"])

    seen: list[str] = []
    for key in keys:
        if key not in seen:
            seen.append(key)
    return seen


def build_all_periods(
    contribution_history: pd.DataFrame,
    weight_history: pd.DataFrame | None,
    *,
    rebalance_start: Any = None,
    directions: dict[str, str] | None = None,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Precompute every standard window. Each one is a subtraction, so this is cheap."""
    if contribution_history is None or contribution_history.empty:
        return []

    results = []
    for key in standard_periods(contribution_history.index, rebalance_start=rebalance_start):
        try:
            built = build_period_analytics(
                contribution_history,
                weight_history,
                key,
                rebalance_start=rebalance_start,
                directions=directions,
                top_n=top_n,
                include_positions=False,
            )
        except ValueError:
            continue
        if built and built["metrics"]["positionsCount"]:
            results.append(built)
    return results
