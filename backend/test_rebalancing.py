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
        expected_net = (1 - daily_drag * 3) * (1 - daily_drag)
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


if __name__ == "__main__":
    unittest.main()
