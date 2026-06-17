import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0SymbolsApiStaticTests(unittest.TestCase):
    def test_symbols_api_exposes_coverage_and_seed(self):
        source = (APP_ROOT / "api" / "v1" / "symbols_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('APIRouter(prefix="/symbols"', source)
        self.assertIn('@router.get("")', source)
        self.assertIn('@router.post("/seed")', source)
        self.assertIn("DEFAULT_SYMBOLS", source)
        self.assertIn("candle_count", source)
        self.assertIn("freshness_status", source)

    def test_main_wires_symbols_api(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("symbols_api.router", source)


if __name__ == "__main__":
    unittest.main()
