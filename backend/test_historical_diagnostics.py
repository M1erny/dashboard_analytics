import unittest

import numpy as np
import pandas as pd

import risk


class HistoricalDiagnosticsTests(unittest.TestCase):
    def test_drawdown_uses_running_peak(self):
        values = pd.Series([1.0, 1.10, 1.04, 0.88, 0.95, 1.12])

        drawdown = risk.calculate_drawdown_series(values)

        self.assertAlmostEqual(drawdown.iloc[0], 0.0)
        self.assertAlmostEqual(drawdown.iloc[1], 0.0)
        self.assertAlmostEqual(drawdown.iloc[3], (0.88 - 1.10) / 1.10)
        self.assertAlmostEqual(drawdown.min(), -0.20)
        self.assertAlmostEqual(drawdown.iloc[-1], 0.0)

    def test_drawdown_from_returns_includes_initial_base_value(self):
        dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"])
        returns = pd.Series([-0.10, 0.0555555556], index=dates[1:])

        values = risk.value_series_from_returns(returns, start_index=dates[0])
        drawdown = risk.calculate_drawdown_series(values)

        self.assertAlmostEqual(values.loc[dates[0]], 1.0)
        self.assertAlmostEqual(values.loc[dates[1]], 0.90)
        self.assertAlmostEqual(drawdown.loc[dates[1]], -0.10)
        self.assertAlmostEqual(drawdown.loc[dates[2]], -0.05, places=8)
        self.assertAlmostEqual(drawdown.min(), -0.10)

    def test_beta_matches_ols_sample_variance(self):
        np.random.seed(7)
        benchmark = pd.Series(np.random.normal(0.001, 0.012, 250))
        portfolio = 1.35 * benchmark + pd.Series(np.random.normal(0, 0.004, 250))

        beta = risk.calculate_beta(portfolio, benchmark)
        ols_beta = np.polyfit(benchmark, portfolio, 1)[0]

        self.assertAlmostEqual(beta, ols_beta, places=10)

    def test_batting_average_tracks_cumulative_contribution_flip(self):
        dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"])
        values = pd.Series([1.0, 1.02, 1.01, 0.99], index=dates)
        benchmark = pd.Series([0.01, -0.004, -0.006], index=dates[1:])
        contribution_history = pd.DataFrame(
            {
                "ROUND_TRIP": [0.0, 0.02, 0.01, -0.01],
            },
            index=dates,
        )

        diagnostics = risk.build_historical_diagnostics(values, benchmark, contribution_history, min_beta_periods=2)

        by_date = {row["date"]: row for row in diagnostics}
        self.assertEqual(by_date["2026-01-02"]["winnersCount"], 1)
        self.assertEqual(by_date["2026-01-02"]["losersCount"], 0)
        self.assertAlmostEqual(by_date["2026-01-02"]["battingAverage"], 1.0)
        self.assertEqual(by_date["2026-01-06"]["winnersCount"], 0)
        self.assertEqual(by_date["2026-01-06"]["losersCount"], 1)
        self.assertAlmostEqual(by_date["2026-01-06"]["battingAverage"], 0.0)

    def test_rebalanced_nav_chains_drawdown_and_variance(self):
        dates = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06"])
        prices = pd.DataFrame(
            {
                "A": [100.0, 110.0, 121.0, 121.0],
                "B": [100.0, 100.0, 90.0, 80.0],
            },
            index=dates,
        )
        snapshots = [
            {
                "date": "2025-12-31",
                "executionTiming": "effective_open",
                "positions": {"A": {"weight": 1.0, "type": "Long"}},
            },
            {
                "date": "2026-01-05",
                "executionTiming": "effective_open",
                "positions": {"B": {"weight": 1.0, "type": "Long"}},
            },
        ]
        original = risk.get_rebalance_snapshots
        risk.get_rebalance_snapshots = lambda _name, _config: snapshots
        try:
            result = risk.calculate_segmented_ytd(
                prices,
                "test",
                snapshots[-1]["positions"],
                "2025-12-31",
                margin_rate=0.0,
                borrow_fee=0.0,
            )
        finally:
            risk.get_rebalance_snapshots = original

        values = result["portfolio_val_series"]
        expected = pd.Series([1.0, 1.10, 0.99, 0.88], index=dates)
        pd.testing.assert_series_equal(values, expected)

        drawdown = risk.calculate_drawdown_series(values)
        self.assertAlmostEqual(drawdown.min(), (0.88 - 1.10) / 1.10)

        returns = values.pct_change().dropna()
        diagnostics = risk.build_historical_diagnostics(values, pd.Series(dtype=float))
        self.assertAlmostEqual(diagnostics[-1]["variance"], returns.var(ddof=1))

    def test_latest_patch_prefers_fresh_warsaw_quote_over_stale_yahoo_quote(self):
        patch_price, patch_source = risk.select_latest_patch_price(
            last_price=33.50,
            previous_close=22.50,
            regular_previous_close=24.80,
            open_val=None,
            volume_val=0,
            qtype="MUTUALFUND",
            market_quote={"price": 26.60, "source": "BiznesRadar"},
        )

        self.assertEqual(patch_price, 26.60)
        self.assertEqual(patch_source, "BiznesRadar")

    def test_latest_patch_uses_regular_previous_close_before_stale_previous_close(self):
        patch_price, patch_source = risk.select_latest_patch_price(
            last_price=33.50,
            previous_close=22.50,
            regular_previous_close=24.80,
            open_val=None,
            volume_val=0,
            qtype="MUTUALFUND",
            market_quote=None,
        )

        self.assertEqual(patch_price, 24.80)
        self.assertEqual(patch_source, "regularMarketPreviousClose")


if __name__ == "__main__":
    unittest.main()
