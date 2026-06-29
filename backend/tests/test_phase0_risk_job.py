import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.risk_job import RiskJob, RiskJobConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0RiskJobTests(unittest.TestCase):
    def setUp(self):
        self.source = (APP_ROOT / "jobs" / "risk_job.py").read_text(encoding="utf-8")

    def test_risk_job_does_not_read_price_or_atr_from_fusion_signal(self):
        self.assertNotIn("s.current_price", self.source)
        self.assertNotIn("s.atr", self.source)
        self.assertIn("latest_market_candle(db, symbol, timeframe)", self.source)
        # self.assertIn("price = float(candle.close_price)", self.source)
        # self.assertIn('getattr(feature, "ATR", None)', self.source)

    # def test_fusion_decisions_are_normalized_for_risk_engine(self):
    #     self.assertIn('{"BULLISH","STRONG_LONG", "LONG", "BUY"}', self.source)
    #     self.assertIn('{"STRONG_SHORT", "SHORT", "SELL"}', self.source)
    #     self.assertIn('return "WAIT"', self.source)

   
    # def test_resolve_risk_inputs_falls_back_to_price_percent_atr(self):
    #     self.assertIn("default_atr_percent = 0.01", self.source)
    #     self.assertIn("atr = price * default_atr_percent", self.source)
    #     self.assertIn('confidence": float(signal.confidence or 0)', self.source)

    def test_risk_repository_can_save_reject_payload_shape(self):
        source = (APP_ROOT / "repositories" / "risk_repository.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('targets = data.get("targets") or {}', source)
        self.assertIn('"entry_price": data.get("entry")', source)
        # self.assertIn('target1=targets.get("t1")', source)

    def test_risk_job_approves_open_trade_plans(self):
        db = Mock()

        trade = SimpleNamespace(
            id=10,
            symbol="BTCUSDT",
            timeframe="5m",
            side="LONG",
            entry_price=100.0,
            stop_loss=99.0,
            target1=102.0,
            target2=103.0,
            confidence=80.0,
            thesis_id=1,
        )

        trade_plan_repo = Mock()
        trade_plan_repo.get_open_trades.return_value = [trade]

        risk_repo = Mock()

        engine = Mock()
        engine.analyze_trade_plan.return_value = {
            "decision": "APPROVE",
            "reason": "Trade plan passed risk checks",
            "risk_reward": 2.0,
            "position_size": 10.0,
            "targets": {
                "t1": 102.0,
                "t2": 103.0,
            },
        }

        job = RiskJob(
            trade_plan_repo=trade_plan_repo,
            risk_repo=risk_repo,
            engine=engine,
        )

        summary = job._approve_trade_plans(db)

        assert summary["processed"] == 1
        assert summary["persisted"] == 1
        assert summary["approved"] == 1
        assert summary["rejected"] == 0

        risk_repo.save.assert_called_once()
        db.commit.assert_called_once()

    def test_resolve_market_inputs_falls_back_to_price_percent_atr(self):
        db = Mock()
        candle = SimpleNamespace(
            close_price=100.0,
            close_time=None,
        )
        job = RiskJob(
            config=RiskJobConfig(
                allow_atr_fallback=True,
                default_atr_percent=0.01,
            ),
        )
        with patch(
            "app.jobs.risk_job.latest_market_candle",
            return_value=candle,
        ), patch.object(
            job,
            "_get_latest_feature",
            return_value=None,
        ):
            result = job._resolve_market_inputs(
                db=db,
                symbol="BTCUSDT",
                timeframe="5m",
            )

        assert result["price"] == 100.0
        assert result["atr"] == 1.0
        assert result["atr_source"] == "PRICE_PERCENT_FALLBACK"


if __name__ == "__main__":
    unittest.main()
