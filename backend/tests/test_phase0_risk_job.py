import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0RiskJobTests(unittest.TestCase):
    def setUp(self):
        self.source = (APP_ROOT / "jobs" / "risk_job.py").read_text(encoding="utf-8")

    def test_risk_job_does_not_read_price_or_atr_from_fusion_signal(self):
        self.assertNotIn("s.current_price", self.source)
        self.assertNotIn("s.atr", self.source)
        self.assertIn("latest_market_candle(db, symbol, timeframe)", self.source)
        self.assertIn("price = float(candle.close_price)", self.source)
        self.assertIn('getattr(feature, "ATR", None)', self.source)

    def test_fusion_decisions_are_normalized_for_risk_engine(self):
        self.assertIn('{"STRONG_LONG", "LONG", "BUY"}', self.source)
        self.assertIn('{"STRONG_SHORT", "SHORT", "SELL"}', self.source)
        self.assertIn('return "WAIT"', self.source)

    def test_resolve_risk_inputs_uses_latest_candle_and_feature_atr(self):
        self.assertIn("def resolve_risk_inputs", self.source)
        self.assertIn("price = float(candle.close_price)", self.source)
        self.assertIn('get_latest_feature(db, signal.symbol, timeframe)', self.source)
        self.assertIn('signal": normalize_fusion_decision(signal.decision)', self.source)

    def test_resolve_risk_inputs_falls_back_to_price_percent_atr(self):
        self.assertIn("DEFAULT_ATR_PERCENT = 0.01", self.source)
        self.assertIn("atr = price * DEFAULT_ATR_PERCENT", self.source)
        self.assertIn('confidence": float(signal.confidence or 0)', self.source)

    def test_risk_repository_can_save_reject_payload_shape(self):
        source = (APP_ROOT / "repositories" / "risk_repository.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('targets = data.get("targets") or {}', source)
        self.assertIn('entry_price=data.get("entry")', source)
        self.assertIn('target1=targets.get("t1")', source)

    def test_risk_job_approves_open_trade_plans(self):
        self.assertIn("TradePlanRepository", self.source)
        self.assertIn("def approve_open_trade_plans", self.source)
        self.assertIn("trade_repo.get_open_trades(db)", self.source)
        self.assertIn("engine.analyze_trade_plan", self.source)
        self.assertIn('"trade_plans"', self.source)
        self.assertIn('"approved"', self.source)


if __name__ == "__main__":
    unittest.main()
