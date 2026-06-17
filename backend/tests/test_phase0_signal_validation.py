import unittest

from app.utils.signal_validation import validate_trade_plan_direction


class Phase0SignalValidationTests(unittest.TestCase):
    def test_long_target_must_be_above_entry(self):
        result = validate_trade_plan_direction("LONG", 1.1207, 1.09829)

        self.assertFalse(result["is_valid"])
        self.assertIn("LONG target_price must be greater than entry_price", result["errors"])

    def test_short_target_must_be_below_entry(self):
        result = validate_trade_plan_direction("SHORT", 1.1207, 1.15)

        self.assertFalse(result["is_valid"])
        self.assertIn("SHORT target_price must be less than entry_price", result["errors"])

    def test_wait_does_not_require_trade_prices(self):
        result = validate_trade_plan_direction("WAIT", None, None)

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
