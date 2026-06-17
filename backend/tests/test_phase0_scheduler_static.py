import unittest
from pathlib import Path

from app.scheduler.registry import get_job_definition
from app.scheduler.registry import resolve_job_ids


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0SchedulerStaticTests(unittest.TestCase):
    def test_default_scheduler_job_is_market_only(self):
        self.assertEqual(resolve_job_ids([]), ["market"])

    def test_known_job_definitions_are_lazy_import_metadata(self):
        market = get_job_definition("market")

        self.assertEqual(market.module, "app.jobs.market_job")
        self.assertEqual(market.function, "run_market_job")
        self.assertEqual(market.seconds, 30)

    def test_regime_job_is_registered_for_fresh_ai_inputs(self):
        regime = get_job_definition("regime")

        self.assertIsNotNone(regime)
        self.assertEqual(regime.module, "app.jobs.regime_jobs")
        self.assertEqual(regime.function, "run_regime_job")
        self.assertEqual(regime.minutes, 1)

    def test_watchlist_persist_job_is_registered_for_ready_setups(self):
        job = get_job_definition("watchlist-persist")

        self.assertIsNotNone(job)
        self.assertEqual(job.id, "watchlist_persist")
        self.assertEqual(job.module, "app.jobs.watchlist_persist_job")
        self.assertEqual(job.function, "run_watchlist_persist_job")
        self.assertEqual(job.seconds, 120)
        self.assertEqual(resolve_job_ids(["watchlist-persist"]), ["watchlist_persist"])

    def test_scheduler_api_exposes_dry_run_not_global_start_only(self):
        source = (APP_ROOT / "api" / "v1" / "scheduler_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("/jobs/{job_id}/dry-run", source)
        self.assertIn("IMPORT_OK", source)
        self.assertIn("EXECUTION_OK", source)

    def test_watchlist_persist_job_reuses_ready_persistence(self):
        source = (APP_ROOT / "jobs" / "watchlist_persist_job.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("persist_ready_watchlist_setups_for_stack", source)
        self.assertIn('mode="intraday"', source)

    def test_pipeline_cycle_job_is_registered_for_end_to_end_loop(self):
        job = get_job_definition("pipeline-cycle")

        self.assertIsNotNone(job)
        self.assertEqual(job.id, "pipeline_cycle")
        self.assertEqual(job.module, "app.jobs.pipeline_cycle_job")
        self.assertEqual(job.function, "run_pipeline_cycle_job")
        self.assertEqual(job.seconds, 120)
        self.assertEqual(resolve_job_ids(["pipeline-cycle"]), ["pipeline_cycle"])

    def test_pipeline_cycle_job_runs_required_stages_in_order(self):
        source = (APP_ROOT / "jobs" / "pipeline_cycle_job.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("run_watchlist_persist_job", source)
        self.assertIn("run_risk_job", source)
        self.assertIn("run_paper_trade_execute_job", source)
        self.assertIn("run_paper_trade_monitor_job", source)
        self.assertIn('"watchlist_persist"', source)
        self.assertIn('"risk"', source)
        self.assertIn('"paper_trade_execute"', source)
        self.assertIn('"paper_trade_monitor"', source)
        self.assertIn('"source": "pipeline_cycle"', source)

    def test_scheduler_startup_is_dependency_safe(self):
        source = (APP_ROOT / "scheduler" / "scheduler.py").read_text(encoding="utf-8")

        self.assertIn("except ModuleNotFoundError", source)
        self.assertIn("return False", source)

    def test_main_wires_scheduler_api(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("scheduler_api.router", source)


if __name__ == "__main__":
    unittest.main()
