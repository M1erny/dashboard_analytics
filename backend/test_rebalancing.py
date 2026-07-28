import unittest

import pandas as pd

import risk


class RebalanceAccountingTests(unittest.TestCase):
    def test_segmented_ytd_chains_old_and_new_books(self):
        dates = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06"])
        prices = pd.DataFrame(
            {
                "OLD": [100.0, 110.0, 999.0, 999.0],
                "NEW": [100.0, 100.0, 100.0, 110.0],
            },
            index=dates,
        )

        old_get_snapshots = risk.get_rebalance_snapshots
        try:
            risk.get_rebalance_snapshots = lambda _name, _active: [
                {
                    "date": "2026-01-01",
                    "label": "Opening book",
                    "source": "test",
                    "positions": {
                        "OLD": {"weight": 1.0, "type": "Long", "currency": "USD"}
                    },
                },
                {
                    "date": "2026-01-05",
                    "label": "Rebalance",
                    "source": "test",
                    "positions": {
                        "NEW": {"weight": 1.0, "type": "Long", "currency": "USD"}
                    },
                },
            ]

            result = risk.calculate_segmented_ytd(
                prices,
                "main",
                {"NEW": {"weight": 1.0, "type": "Long", "currency": "USD"}},
                "2026-01-01",
                0.0,
                0.0,
            )
        finally:
            risk.get_rebalance_snapshots = old_get_snapshots

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["ytd_return"], 0.21, places=8)
        self.assertAlmostEqual(result["position_contributions"]["OLD"], 0.10, places=8)
        self.assertAlmostEqual(result["position_contributions"]["NEW"], 0.11, places=8)
        self.assertEqual(result["current_weights"]["NEW"], 1.0)

    def test_financing_drag_restarts_from_high_leverage_rebalance(self):
        dates = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06"])
        prices = pd.DataFrame(
            {
                "LOW": [100.0, 100.0, 100.0, 100.0],
                "HIGH": [100.0, 100.0, 100.0, 100.0],
                "SHORT": [100.0, 100.0, 100.0, 100.0],
            },
            index=dates,
        )

        margin_rate = 0.10
        borrow_fee = 0.02
        daily_drag = ((1.5 - 1.0) * margin_rate + 1.0 * borrow_fee) / 360
        # The dated book is live for the three-day weekend interval and the
        # following session. Margin debt is fixed at the opening notional.
        expected_net = 1 - daily_drag * 4
        expected_financing_cost = 1 - expected_net

        old_get_snapshots = risk.get_rebalance_snapshots
        try:
            risk.get_rebalance_snapshots = lambda _name, _active: [
                {
                    "date": "2026-01-01",
                    "label": "Low leverage opening book",
                    "source": "test",
                    "positions": {
                        "LOW": {"weight": 1.0, "type": "Long", "currency": "USD"}
                    },
                },
                {
                    "date": "2026-01-05",
                    "label": "High leverage rebalance",
                    "source": "test",
                    "positions": {
                        "HIGH": {"weight": 1.5, "type": "Long", "currency": "USD"},
                        "SHORT": {"weight": 1.0, "type": "Short", "currency": "USD"},
                    },
                },
            ]

            result = risk.calculate_segmented_ytd(
                prices,
                "main",
                {
                    "HIGH": {"weight": 1.5, "type": "Long", "currency": "USD"},
                    "SHORT": {"weight": 1.0, "type": "Short", "currency": "USD"},
                },
                "2026-01-01",
                margin_rate,
                borrow_fee,
            )
        finally:
            risk.get_rebalance_snapshots = old_get_snapshots

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["ytd_return_gross"], 0.0, places=8)
        self.assertAlmostEqual(result["ytd_return"], -expected_financing_cost, places=8)
        self.assertAlmostEqual(result["ytd_financing_cost"], expected_financing_cost, places=8)

        opening_event, rebalance_event = result["rebalance_events"]
        self.assertAlmostEqual(opening_event["annualFinancingCost"], 0.0, places=8)
        self.assertAlmostEqual(opening_event["segmentFinancingCost"], 0.0, places=8)
        self.assertAlmostEqual(rebalance_event["dailyFinancingDrag"], daily_drag, places=10)
        self.assertAlmostEqual(rebalance_event["annualFinancingCost"], daily_drag * 360, places=8)
        self.assertAlmostEqual(rebalance_event["segmentFinancingCost"], expected_financing_cost, places=8)
        self.assertAlmostEqual(rebalance_event["cumulativeFinancingCost"], expected_financing_cost, places=8)

    def test_current_weight_is_measured_against_net_nav_after_financing(self):
        dates = pd.to_datetime(["2025-12-31", "2026-01-02"])
        prices = pd.DataFrame({"LONG": [100.0, 100.0]}, index=dates)
        margin_rate = 0.18

        old_get_snapshots = risk.get_rebalance_snapshots
        try:
            risk.get_rebalance_snapshots = lambda _name, _active: [
                {
                    "date": "2026-01-01",
                    "label": "Levered opening book",
                    "source": "test",
                    "positions": {
                        "LONG": {"weight": 1.5, "type": "Long", "currency": "USD"},
                    },
                },
            ]
            result = risk.calculate_segmented_ytd(
                prices,
                "main",
                {"LONG": {"weight": 1.5, "type": "Long", "currency": "USD"}},
                "2026-01-01",
                margin_rate,
                0.0,
            )
        finally:
            risk.get_rebalance_snapshots = old_get_snapshots

        expected_cost = (1.5 - 1.0) * margin_rate * 2 / 360
        expected_net_nav = 1.0 - expected_cost
        self.assertAlmostEqual(result["portfolio_val_series"].iloc[-1], expected_net_nav, places=10)
        self.assertAlmostEqual(result["current_weights"]["LONG"], 1.5 / expected_net_nav, places=10)
        self.assertGreater(result["current_weights"]["LONG"], 1.5)

    def test_post_session_rebalance_starts_after_close(self):
        dates = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06"])
        prices = pd.DataFrame(
            {
                "OLD": [100.0, 110.0, 120.0, 999.0],
                "NEW": [50.0, 50.0, 50.0, 55.0],
            },
            index=dates,
        )

        old_get_snapshots = risk.get_rebalance_snapshots
        try:
            risk.get_rebalance_snapshots = lambda _name, _active: [
                {
                    "date": "2026-01-01",
                    "label": "Opening book",
                    "source": "test",
                    "positions": {
                        "OLD": {"weight": 1.0, "type": "Long", "currency": "USD"}
                    },
                },
                {
                    "date": "2026-01-05",
                    "label": "After-close rebalance",
                    "source": "test",
                    "executionTiming": "post_session",
                    "positions": {
                        "NEW": {"weight": 1.0, "type": "Long", "currency": "USD"}
                    },
                },
            ]

            result = risk.calculate_segmented_ytd(
                prices,
                "main",
                {"NEW": {"weight": 1.0, "type": "Long", "currency": "USD"}},
                "2026-01-01",
                0.0,
                0.0,
            )
        finally:
            risk.get_rebalance_snapshots = old_get_snapshots

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["ytd_return"], 0.32, places=8)
        self.assertAlmostEqual(result["position_contributions"]["OLD"], 0.20, places=8)
        self.assertAlmostEqual(result["position_contributions"]["NEW"], 0.12, places=8)
        self.assertEqual(result["current_weights"]["NEW"], 1.0)
        self.assertEqual(result["rebalance_events"][1]["date"], "2026-01-05")
        self.assertEqual(result["rebalance_events"][1]["executionTiming"], "post_session")

    def test_same_ticker_rebalance_adds_contribution_once(self):
        dates = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06"])
        prices = pd.DataFrame(
            {
                "KEEP": [100.0, 110.0, 110.0, 121.0],
            },
            index=dates,
        )

        old_get_snapshots = risk.get_rebalance_snapshots
        try:
            risk.get_rebalance_snapshots = lambda _name, _active: [
                {
                    "date": "2026-01-01",
                    "label": "Opening book",
                    "source": "test",
                    "positions": {
                        "KEEP": {"weight": 1.0, "type": "Long", "currency": "USD"}
                    },
                },
                {
                    "date": "2026-01-05",
                    "label": "Increase same name after close",
                    "source": "test",
                    "executionTiming": "post_session",
                    "positions": {
                        "KEEP": {"weight": 2.0, "type": "Long", "currency": "USD"}
                    },
                },
            ]

            result = risk.calculate_segmented_ytd(
                prices,
                "main",
                {"KEEP": {"weight": 2.0, "type": "Long", "currency": "USD"}},
                "2026-01-01",
                0.0,
                0.0,
            )
        finally:
            risk.get_rebalance_snapshots = old_get_snapshots

        self.assertIsNotNone(result)
        expected_first_segment = 0.10
        expected_second_segment = 1.10 * 2.0 * 0.10
        self.assertAlmostEqual(
            result["position_contributions"]["KEEP"],
            expected_first_segment + expected_second_segment,
            places=8,
        )
        self.assertAlmostEqual(
            result["latest_segment_position_contributions"]["KEEP"],
            0.20,
            places=8,
        )
        self.assertAlmostEqual(
            result["latest_segment_position_contributions_ytd_basis"]["KEEP"],
            expected_second_segment,
            places=8,
        )
        self.assertAlmostEqual(result["ytd_return"], 0.32, places=8)
        self.assertEqual(list(result["position_contributions"].keys()), ["KEEP"])

    def test_post_session_seam_day_survives_in_long_short_split(self):
        """A post_session rebalance must not erase its seam day from the L/S split.

        The new segment's index starts ON the rebalance close, where diff() is NaN.
        Filling that row with 0.0 used to overwrite the real long/short returns the
        previous segment had already written there, so longOnlyBeta + shortOnlyBeta
        stopped summing to the portfolio beta by exactly that one day.
        """
        dates = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06"])
        prices = pd.DataFrame(
            {
                "LONG": [100.0, 100.0, 110.0, 110.0],
                "SHORT": [100.0, 100.0, 90.0, 90.0],
                "NEW": [100.0, 100.0, 100.0, 100.0],
            },
            index=dates,
        )
        # 2026-01-05 is the rebalance close and the only day either leg moves:
        # LONG +10% at weight 1.0 and SHORT -10% at weight 0.25 both help the book.
        old_get_snapshots = risk.get_rebalance_snapshots
        try:
            risk.get_rebalance_snapshots = lambda _name, _active: [
                {
                    "date": "2026-01-01",
                    "label": "Opening book",
                    "source": "test",
                    "executionTiming": "effective_open",
                    "positions": {
                        "LONG": {"weight": 1.0, "type": "Long", "currency": "USD"},
                        "SHORT": {"weight": 0.25, "type": "Short", "currency": "USD"},
                    },
                },
                {
                    "date": "2026-01-05",
                    "label": "Post-session rebalance",
                    "source": "test",
                    "executionTiming": "post_session",
                    "positions": {
                        "NEW": {"weight": 1.0, "type": "Long", "currency": "USD"}
                    },
                },
            ]

            result = risk.calculate_segmented_ytd(
                prices,
                "main",
                {"NEW": {"weight": 1.0, "type": "Long", "currency": "USD"}},
                "2026-01-05",
                0.0,
                0.0,
            )
        finally:
            risk.get_rebalance_snapshots = old_get_snapshots

        self.assertIsNotNone(result)
        seam = pd.Timestamp("2026-01-05")
        long_ret = result["long_daily_ret"]
        short_ret = result["short_daily_ret"]

        # The seam day's real decomposition must still be there, not zeroed.
        self.assertAlmostEqual(long_ret.loc[seam], 0.10, places=10)
        self.assertAlmostEqual(short_ret.loc[seam], 0.025, places=10)

        # And the split must reconstruct the portfolio's own return on that day.
        gross = result["portfolio_val_series_gross"]
        seam_total = gross.loc[seam] / gross.loc[pd.Timestamp("2026-01-02")] - 1.0
        self.assertAlmostEqual(long_ret.loc[seam] + short_ret.loc[seam], seam_total, places=10)

        # The first date of the whole series has no prior day, so it stays flat.
        self.assertAlmostEqual(long_ret.iloc[0], 0.0, places=12)
        self.assertAlmostEqual(short_ret.iloc[0], 0.0, places=12)


class BattingStatsTests(unittest.TestCase):
    def test_untraded_names_are_excluded_from_the_denominator(self):
        """Names added at a post_session rebalance have no return day yet.

        Their cumulative contribution is exactly 0.0 on the rebalance date. Counting
        them printed a one-day collapse in hit rate at every dated rebalance.
        """
        row = pd.Series({"WIN": 0.05, "LOSE": -0.02, "ADDED_TODAY": 0.0, "ALSO_ADDED": 0.0})
        stats = risk.calculate_batting_stats(row)

        self.assertEqual(stats["positionsCount"], 2)
        self.assertEqual(stats["winnersCount"], 1)
        self.assertEqual(stats["losersCount"], 1)
        self.assertAlmostEqual(stats["battingAverage"], 0.5, places=10)

    def test_all_flat_row_reports_no_batting_average(self):
        stats = risk.calculate_batting_stats(pd.Series({"A": 0.0, "B": 0.0}))
        self.assertEqual(stats["positionsCount"], 0)
        self.assertTrue(pd.isna(stats["battingAverage"]))


if __name__ == "__main__":
    unittest.main()
