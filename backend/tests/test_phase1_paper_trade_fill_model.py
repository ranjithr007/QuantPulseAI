import unittest
from types import SimpleNamespace

from app.paper_trading.fill_model import build_fill_profile
from app.paper_trading.fill_model import simulate_exit_fill


class Phase1PaperTradeFillModelTests(unittest.TestCase):
    def test_build_fill_profile_long_applies_adverse_entry_slippage(self):
        profile = build_fill_profile(
            side="LONG",
            planned_entry_price=100,
            stop_loss=99,
            target1=102,
            confidence=50,
            risk_reward=2,
        )

        self.assertEqual(profile["model"], "paper_trade_fill_model_v1")
        self.assertEqual(profile["side"], "LONG")
        self.assertEqual(profile["entry_fill_price"], 100.06)
        self.assertEqual(profile["entry_slippage_pct"], 0.06)
        self.assertEqual(profile["fill_quality"], "NORMAL")
        self.assertEqual(profile["effective_risk_reward"], 1.83)

    def test_build_fill_profile_short_applies_adverse_entry_slippage(self):
        profile = build_fill_profile(
            side="SHORT",
            planned_entry_price=100,
            stop_loss=101,
            target1=98,
            confidence=80,
            risk_reward=2,
        )

        self.assertEqual(profile["side"], "SHORT")
        self.assertEqual(profile["entry_fill_price"], 99.97)
        self.assertEqual(profile["entry_slippage_pct"], 0.035)
        self.assertEqual(profile["fill_quality"], "TIGHT")
        self.assertEqual(profile["effective_risk_reward"], 1.91)

    def test_simulate_exit_fill_uses_adverse_slippage_on_close(self):
        trade = SimpleNamespace(
            side="LONG",
            stop_loss=99.0,
            target1=102.0,
            confidence=50,
            entry_price=100.0,
            risk_reward=2.0,
        )

        target_fill = simulate_exit_fill(trade, 102.0, "TARGET")
        stop_fill = simulate_exit_fill(trade, 99.0, "STOP")

        self.assertEqual(target_fill["exit_fill_price"], 101.96)
        self.assertEqual(target_fill["trigger_type"], "TARGET")
        self.assertEqual(stop_fill["exit_fill_price"], 98.9257)
        self.assertEqual(stop_fill["trigger_type"], "STOP")


if __name__ == "__main__":
    unittest.main()
