import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0TradePlanApiStaticTests(unittest.TestCase):
    def test_trade_plan_api_route_exists(self):
        source = (APP_ROOT / "api" / "v1" / "trade_plan_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('APIRouter(prefix="/trade-plan"', source)
        self.assertIn('@router.get("/{symbol}")', source)
        self.assertIn("freshness_status", source)
        self.assertIn("validate_trade_plan_direction", source)

    def test_main_wires_trade_plan_api(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("trade_plan_api.router", source)

    def test_trade_plan_repository_can_save_ready_watchlist_plan(self):
        source = (APP_ROOT / "repositories" / "trade_plan_repository.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def save_ready_trade_plan", source)
        self.assertIn('target3=None', source)
        self.assertIn('status="OPEN"', source)


if __name__ == "__main__":
    unittest.main()
