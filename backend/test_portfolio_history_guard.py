import unittest

from validate_portfolio_history import validate_portfolio_history


class PortfolioHistoryGuardTests(unittest.TestCase):
    def test_main_portfolio_history_is_valid(self):
        errors, _warnings = validate_portfolio_history("main")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
