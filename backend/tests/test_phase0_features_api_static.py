import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0FeaturesApiStaticTests(unittest.TestCase):
    def test_features_api_exposes_feature_quality_route(self):
        source = (APP_ROOT / "api" / "v1" / "features_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('APIRouter(prefix="/features"', source)
        self.assertIn('@router.get("/{symbol}/quality")', source)
        self.assertIn("build_feature_quality_profile", source)
        self.assertIn("get_latest_candles", source)
        self.assertIn("feature_quality_engine", source)


if __name__ == "__main__":
    unittest.main()
