import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0PlaceholderCleanupTests(unittest.TestCase):
    def test_core_placeholder_modules_are_not_empty(self):
        paths = [
            APP_ROOT / "api" / "v1" / "market_api.py",
            APP_ROOT / "api" / "v1" / "regime_api.py",
            APP_ROOT / "api" / "v1" / "ai_scores_api.py",
            APP_ROOT / "api" / "v1" / "indicators_api.py",
            APP_ROOT / "api" / "v1" / "intelligence_api.py",
            APP_ROOT / "engines" / "technical_engine.py",
            APP_ROOT / "engines" / "volatility_engine.py",
            APP_ROOT / "engines" / "derivative_engine.py",
            APP_ROOT / "engines" / "sentiment_engine.py",
            APP_ROOT / "engines" / "regime_engine.py",
            APP_ROOT / "risk" / "drawdown_engine.py",
        ]

        for path in paths:
            with self.subTest(path=path.name):
                self.assertGreater(path.stat().st_size, 0)

    def test_new_api_routers_are_wired(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        for router in [
            "market_api.router",
            "regime_api.router",
            "ai_scores_api.router",
            "indicators_api.router",
            "intelligence_api.router",
        ]:
            with self.subTest(router=router):
                self.assertIn(router, source)


if __name__ == "__main__":
    unittest.main()
