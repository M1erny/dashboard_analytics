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


if __name__ == "__main__":
    unittest.main()
