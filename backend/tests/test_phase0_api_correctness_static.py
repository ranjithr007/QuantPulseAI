import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0ApiCorrectnessStaticTests(unittest.TestCase):
    def test_master_ai_filters_candle_by_timeframe_and_validates_trade_plan(self):
        source = (APP_ROOT / "api" / "v2" / "master_ai_v2_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("get_latest_candle(db, symbol, timeframe)", source)
        self.assertIn("validate_trade_plan_direction", source)
        self.assertIn("trade_plan_validation", source)
        self.assertIn("current_price", source)

    def test_risk_api_formats_and_validates_historical_decision(self):
        source = (APP_ROOT / "api" / "v1" / "risk_api.py").read_text(encoding="utf-8")

        self.assertIn("validate_trade_plan_direction", source)
        self.assertIn("historical_stale_invalid", source)
        self.assertIn("is_usable", source)
        self.assertIn("Risk decision is stale", source)
        self.assertIn("NO_RISK_DECISION", source)

    def test_fusion_response_preserves_timeframe(self):
        service_source = (APP_ROOT / "services" / "fusion_service.py").read_text(
            encoding="utf-8"
        )
        repo_source = (APP_ROOT / "repositories" / "fusion_repository.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('result["timeframe"] = timeframe', service_source)
        self.assertIn("timeframe=data.get", repo_source)
        self.assertIn('"scores"', service_source)


if __name__ == "__main__":
    unittest.main()
