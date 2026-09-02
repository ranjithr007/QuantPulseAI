import unittest
from pathlib import Path

from app.scheduler.registry import get_job_definition
from app.scheduler.registry import resolve_job_ids


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0SchedulerStaticTests(unittest.TestCase):
    def test_default_scheduler_jobs_cover_paper_pipeline(self):
        self.assertEqual(
            resolve_job_ids([]),
            [
                "deterministic_pipeline",
                "derivative",
                "candle_completeness",
                "liquidations",
                "whales",
                "whale_ai",
                "heatmap",
                "orderbook",
                "walk_forward_queue",
                "pipeline_retention",
            ],
        )

    def test_market_evidence_collectors_are_enabled_by_default(self):
        liquidations = get_job_definition("liquidations")
        whales = get_job_definition("whales")
        whale_ai = get_job_definition("whale_ai")
        heatmap = get_job_definition("heatmap")
        orderbook = get_job_definition("orderbook")

        self.assertEqual(liquidations.trigger, "date")
        self.assertEqual(liquidations.function, "run_liquidation_job")
        self.assertEqual(whales.seconds, 120)
        self.assertEqual(whale_ai.seconds, 120)
        self.assertEqual(heatmap.seconds, 60)
        self.assertEqual(orderbook.minutes, 1)

    def test_operational_pipeline_retention_is_enabled_by_default(self):
        retention = get_job_definition("pipeline-retention")

        self.assertIn("pipeline_retention", resolve_job_ids([]))
        self.assertEqual(retention.function, "run_pipeline_retention_job")
        self.assertEqual(retention.minutes, 24 * 60)

    def test_deterministic_pipeline_is_registered_for_explicit_promotion(self):
        job = get_job_definition("deterministic_pipeline")

        self.assertIsNotNone(job)
        self.assertEqual(job.module, "app.jobs.deterministic_pipeline_job")
        self.assertEqual(job.function, "run_deterministic_pipeline_job")
        self.assertEqual(resolve_job_ids(["deterministic_pipeline"]), ["deterministic_pipeline"])

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
        self.assertIn("return run_regime_analysis(context=context)", self._source("app/jobs/regime_jobs.py"))

    def _source(self, relative_path):
        return (PROJECT_ROOT / "backend" / relative_path).read_text(encoding="utf-8")

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

    def test_scheduler_api_exposes_manual_start(self):
        source = (APP_ROOT / "api" / "v1" / "scheduler_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('@router.post("/start")', source)
        self.assertIn("start_scheduler", source)

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

    def test_walk_forward_queue_runs_on_worker_without_web_request_blocking(self):
        job = get_job_definition("walk-forward-queue")

        self.assertIsNotNone(job)
        self.assertEqual(job.module, "app.jobs.walk_forward_queue_job")
        self.assertEqual(job.function, "run_walk_forward_queue_job")
        self.assertEqual(job.seconds, 10)
        self.assertEqual(job.max_instances, 1)
        self.assertTrue(job.coalesce)

    def test_scheduler_startup_is_dependency_safe(self):
        source = (APP_ROOT / "scheduler" / "scheduler.py").read_text(encoding="utf-8")

        self.assertIn("except ModuleNotFoundError", source)
        self.assertIn("return False", source)

    def test_scheduler_start_can_reconfigure_running_jobs(self):
        source = (APP_ROOT / "scheduler" / "scheduler.py").read_text(encoding="utf-8")

        self.assertIn('action = "Reconfiguring" if scheduler.running else "Starting"', source)
        self.assertIn("scheduler.remove_all_jobs()", source)

    def test_main_wires_scheduler_api(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("scheduler_api.router", source)


if __name__ == "__main__":
    unittest.main()
