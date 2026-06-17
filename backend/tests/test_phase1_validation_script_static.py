import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "backend" / "validate_phase1.ps1"


class Phase1ValidationScriptStaticTests(unittest.TestCase):
    def test_validation_script_runs_full_pipeline_checklist(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("phase1_validation_runs", source)
        self.assertIn("Save-ValidationResult", source)
        self.assertIn("/health", source)
        self.assertIn("/scheduler/jobs", source)
        self.assertIn("/signals/$Symbol", source)
        self.assertIn("/signals/watchlist?mode=$Mode", source)
        self.assertIn("/signals/watchlist/persist-ready?mode=$Mode", source)
        self.assertIn("/signals/$Symbol/diagnostics?timeframe=4h", source)
        self.assertIn("/signals/$Symbol/diagnostics?timeframe=1d", source)
        self.assertIn("/signals/$Symbol/multi-timeframe?mode=swing", source)
        self.assertIn("/signals/$Symbol/multi-timeframe?mode=position", source)
        self.assertIn("/trade-plan/${Symbol}?status=OPEN", source)
        self.assertNotIn("/trade-plan/$Symbol?status=OPEN", source)
        self.assertIn("/scheduler/jobs/risk/dry-run?execute=true", source)
        self.assertIn("/paper-trade/candidates", source)
        self.assertIn("/paper-trade/execute-candidates", source)
        self.assertIn("/paper-trade/trades?status=OPEN", source)
        self.assertIn("/paper-trade/performance", source)
        self.assertIn("/pipeline/status?mode=$Mode", source)
        self.assertIn("/scheduler/jobs/pipeline-cycle/dry-run?execute=true", source)
        self.assertIn("summary.json", source)


if __name__ == "__main__":
    unittest.main()
