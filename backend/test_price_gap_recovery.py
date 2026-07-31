"""Detection of bars the threaded bulk download drops.

yfinance's multi-ticker download intermittently omits individual sessions that a
single-ticker request for the same window returns. Before this guard, a ticker with
almost-complete history was never retried, the hole was forward-filled, and the
previous session's move was reported as today's 1-day return.
"""

import unittest

import numpy as np
import pandas as pd

import risk


def build_frame(dates, tickers):
    columns = pd.MultiIndex.from_product([["Close"], tickers])
    data = np.arange(1.0, len(dates) * len(tickers) + 1.0).reshape(len(dates), len(tickers))
    return pd.DataFrame(data, index=pd.to_datetime(dates), columns=columns)


class RecentSettledGapTests(unittest.TestCase):
    DATES = [
        "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24",
        "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31",
    ]

    def detect(self, frame, tickers):
        """The same detector fetch_data uses, with no network involved."""
        return risk._detect_incomplete_tickers(frame, tickers)

    def test_missing_settled_bar_is_flagged(self):
        frame = build_frame(self.DATES, ["XTB.WA", "NVDA"])
        # Drop only 2026-07-30 for XTB.WA - the exact observed failure.
        frame.loc[pd.Timestamp("2026-07-30"), ("Close", "XTB.WA")] = np.nan
        flagged = self.detect(frame, ["XTB.WA", "NVDA"])
        self.assertIn("XTB.WA", flagged)
        self.assertNotIn("NVDA", flagged)

    def test_healthy_frame_flags_nothing(self):
        frame = build_frame(self.DATES, ["XTB.WA", "NVDA"])
        self.assertEqual(self.detect(frame, ["XTB.WA", "NVDA"]), [])

    def test_pending_last_row_is_not_flagged(self):
        """Before a venue opens its final bar is legitimately absent.

        That case is handled by the fast_info patch, so it must not trigger a retry.
        """
        frame = build_frame(self.DATES, ["NVDA"])
        frame.loc[pd.Timestamp("2026-07-31"), ("Close", "NVDA")] = np.nan
        self.assertEqual(self.detect(frame, ["NVDA"]), [])

    def test_completely_missing_ticker_still_flagged(self):
        frame = build_frame(self.DATES, ["XTB.WA"])
        self.assertIn("MISSING", self.detect(frame, ["XTB.WA", "MISSING"]))

    def test_old_gap_outside_the_window_is_ignored(self):
        """A hole in deep history is not recoverable noise worth a retry."""
        frame = build_frame(self.DATES, ["XTB.WA"])
        frame.loc[pd.Timestamp("2026-07-21"), ("Close", "XTB.WA")] = np.nan
        self.assertEqual(self.detect(frame, ["XTB.WA"]), [])

    def test_empty_frame_does_not_crash(self):
        empty = pd.DataFrame()
        self.assertEqual(self.detect(empty, ["XTB.WA"]), ["XTB.WA"])


if __name__ == "__main__":
    unittest.main()
