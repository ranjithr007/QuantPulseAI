import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"
PIPELINE_API = APP_ROOT / "api" / "v1" / "pipeline_api.py"


class Phase1PipelineStatusStaticTests(unittest.TestCase):
    def test_pipeline_status_endpoint_summarizes_end_to_end_flow(self):
        source = PIPELINE_API.read_text(encoding="utf-8")

        self.assertIn('APIRouter(prefix="/pipeline"', source)
        self.assertIn('@router.get("/status")', source)
        self.assertIn('"source": "pipeline_status"', source)
        self.assertIn("build_signal_watchlist_payload", source)
        self.assertIn("lower=None", source)
        self.assertIn("middle=None", source)
        self.assertIn("higher=None", source)
        self.assertIn("failed_max=None", source)
        self.assertIn("TradePlanRepository", source)
        self.assertIn("RiskDecision", source)
        self.assertIn("build_paper_trade_candidates", source)
        self.assertIn("trades=open_trade_plans", source)
        self.assertIn("PaperTradeRepository", source)
        self.assertIn("paper_repo.performance_summary", source)
        self.assertNotIn("paper_repo.all_trades", source)

    def test_pipeline_status_exposes_required_stages_and_blockers(self):
        source = PIPELINE_API.read_text(encoding="utf-8")

        self.assertIn('"watchlist"', source)
        self.assertIn('"trade_plans"', source)
        self.assertIn('"risk"', source)
        self.assertIn('"paper_candidates"', source)
        self.assertIn('"paper_trades"', source)
        self.assertIn('"performance"', source)
        self.assertIn('"blockers"', source)
        self.assertIn("No READY watchlist setups", source)
        self.assertIn("No OPEN trade plans", source)
        self.assertIn("No eligible paper-trade candidates", source)
        self.assertIn("No OPEN paper trades", source)

    def test_main_wires_pipeline_api(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("pipeline_api", source)
        self.assertIn("pipeline_api.router", source)


if __name__ == "__main__":
    unittest.main()
