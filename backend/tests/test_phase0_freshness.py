import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from app.utils.freshness import candle_freshness_timestamp
from app.utils.freshness import freshness_status
from app.utils.freshness import normalize_timestamp_to_utc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0FreshnessTests(unittest.TestCase):
    def test_none_timestamp_is_stale(self):
        status = freshness_status(None, stale_after_seconds=60)

        self.assertTrue(status["is_stale"])
        self.assertIsNone(status["data_age_seconds"])

    def test_recent_timestamp_is_not_stale(self):
        status = freshness_status(
            datetime.now(timezone.utc) - timedelta(seconds=10),
            stale_after_seconds=60,
        )

        self.assertFalse(status["is_stale"])
        self.assertLessEqual(status["data_age_seconds"], 60)

    def test_old_timestamp_is_stale(self):
        status = freshness_status(
            datetime.now(timezone.utc) - timedelta(minutes=20),
            stale_after_seconds=60,
        )

        self.assertTrue(status["is_stale"])
        self.assertGreater(status["data_age_seconds"], 60)

    def test_future_timestamp_is_not_reported_as_fresh(self):
        status = freshness_status(
            datetime.now(timezone.utc) + timedelta(minutes=20),
            stale_after_seconds=60,
        )

        self.assertTrue(status["is_stale"])
        self.assertTrue(status["is_future"])
        self.assertGreater(status["future_by_seconds"], 60)
        self.assertEqual(status["data_age_seconds"], 0)

    def test_candle_freshness_uses_close_boundary(self):
        open_time = datetime.now(timezone.utc) - timedelta(minutes=83)
        close_time = open_time + timedelta(hours=1)
        candle = {
            "candle_time": open_time,
            "close_time": close_time,
        }

        timestamp = candle_freshness_timestamp(candle)
        status = freshness_status(timestamp, stale_after_seconds=65 * 60)

        self.assertEqual(timestamp, close_time)
        self.assertFalse(status["is_stale"])

    def test_normalize_timestamp_to_utc_handles_aware_values(self):
        timestamp = datetime.now(timezone.utc)
        normalized = normalize_timestamp_to_utc(timestamp)

        self.assertEqual(normalized.tzinfo, timezone.utc)

    def test_core_routes_expose_freshness_controls(self):
        route_files = [
            APP_ROOT / "api" / "v1" / "features_api.py",
            APP_ROOT / "api" / "v1" / "orderflow_api.py",
            APP_ROOT / "api" / "v1" / "smc_api.py",
            APP_ROOT / "api" / "v1" / "signals_api.py",
            APP_ROOT / "api" / "v1" / "risk_api.py",
            APP_ROOT / "api" / "v2" / "master_ai_v2_api.py",
            APP_ROOT / "api" / "v2" / "fusion_ai_api.py",
        ]

        for path in route_files:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("stale_after_seconds", source)

    def test_market_candles_are_saved_as_utc_not_local_time(self):
        source = (APP_ROOT / "repositories" / "market_repository.py").read_text(
            encoding="utf-8"
        )
        candle_source = (
            APP_ROOT / "repositories" / "candle_repository.py"
        ).read_text(encoding="utf-8")
        job_source = (APP_ROOT / "jobs" / "market_job.py").read_text(encoding="utf-8")

        self.assertIn("timezone.utc", source)
        self.assertIn("normalize_timestamp_to_utc", candle_source)
        self.assertIn("raw_time_candidates", candle_source)
        self.assertIn("recent_insert_candidates", candle_source)
        self.assertIn("MarketCandle.id.desc()", candle_source)
        self.assertIn("FUTURE_CANDLE_TOLERANCE_SECONDS", candle_source)
        self.assertIn("usable_candidates", candle_source)
        self.assertIn("max_usable_time", source)
        self.assertIn("repo.save_candle(db, candle)", job_source)

    def test_signal_pipeline_models_default_to_utc(self):
        model_files = [
            APP_ROOT / "database" / "models" / "market_order_flow.py",
            APP_ROOT / "database" / "models" / "market_smc.py",
            APP_ROOT / "database" / "models" / "order_flow_signal.py",
            APP_ROOT / "database" / "models" / "fusion_signal.py",
            APP_ROOT / "database" / "models" / "master_signals.py",
            APP_ROOT / "database" / "models" / "risk_decision.py",
            APP_ROOT / "database" / "models" / "risk_signal.py",
            APP_ROOT / "database" / "models" / "trade_plan.py",
        ]

        for path in model_files:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("datetime.utcnow", source)


if __name__ == "__main__":
    unittest.main()
