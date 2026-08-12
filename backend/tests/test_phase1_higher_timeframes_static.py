import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND = PROJECT_ROOT / "backend"


class Phase1HigherTimeframeStaticTests(unittest.TestCase):
    def test_background_jobs_generate_higher_timeframe_inputs(self):
        expected = "TIMEFRAMES = list(OFFICIAL_ENTRY_TIMEFRAMES)"

        for relative_path in [
            "app/jobs/feature_jobs.py",
            "app/jobs/orderflow_jobs.py",
            "app/jobs/smc_job.py",
        ]:
            source = (BACKEND / relative_path).read_text(encoding="utf-8")
            self.assertIn(expected, source, relative_path)

    def test_phase1_validator_covers_higher_timeframe_diagnostics(self):
        source = (BACKEND / "validate_phase1.ps1").read_text(encoding="utf-8")

        self.assertIn("diagnostics_4h", source)
        self.assertIn("diagnostics_1d", source)
        self.assertIn("multi_timeframe_swing", source)
        self.assertIn("multi_timeframe_position", source)


if __name__ == "__main__":
    unittest.main()
