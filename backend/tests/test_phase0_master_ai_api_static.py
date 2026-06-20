import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0MasterAiApiStaticTests(unittest.TestCase):
    def test_master_ai_v1_alias_route_exists(self):
        source = (APP_ROOT / "api" / "v1" / "master_ai_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('APIRouter(prefix="/master-ai"', source)
        self.assertIn('@router.get("/{symbol}")', source)
        self.assertIn("build_master_ai_response", source)

    def test_master_ai_v2_uses_shared_response_builder(self):
        source = (APP_ROOT / "api" / "v2" / "master_ai_v2_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def build_master_ai_response", source)
        self.assertIn("return build_master_ai_response", source)
        self.assertIn("build_contradiction_report", source)
        self.assertIn("build_probability_profile", source)

    def test_main_wires_master_ai_alias(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("master_ai_api.router", source)


if __name__ == "__main__":
    unittest.main()
