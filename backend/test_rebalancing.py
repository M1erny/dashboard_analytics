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


if __name__ == "__main__":
    unittest.main()
