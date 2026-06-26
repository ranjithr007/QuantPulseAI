import unittest
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from app.intelligence.data_quality_ledger import build_data_quality_events
from app.intelligence.data_quality_ledger import build_data_quality_observability


START = datetime(2026, 1, 1, 12, 0, 0)


def candle(offset_minutes, close_price, volume):
    return SimpleNamespace(
        symbol="BTCUSDT",
        timeframe="5m",
        candle_time=START + timedelta(minutes=offset_minutes),
        close_price=close_price,
        volume=volume,
    )


class Phase0DataQualityLedgerTests(unittest.TestCase):
    def test_build_data_quality_events_captures_blocking_staleness_and_cross_source_issues(self):
        report = {
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "status": "INVALIDATED",
            "trade_allowed": False,
            "conflict_score": 80,
            "freshness": {
                "candle": {"is_stale": True},
                "feature": {"is_stale": False},
                "regime": {"is_stale": True},
                "orderflow": {"is_stale": False},
                "smc": {"is_stale": False},
            },
            "conflicts": [
                {
                    "name": "feature_regime_mismatch",
                    "severity": "critical",
                    "detail": "Feature trend and regime are pointing in different directions",
                }
            ],
            "funding_rate": 0.002,
            "open_interest_change_pct": 18.0,
            "candle_time": START + timedelta(minutes=2),
        }
        candles = [
            candle(2, 110.0, 300.0),
            candle(1, 100.0, 50.0),
        ]

        events = build_data_quality_events(report, candles=candles)

        categories = {event["category"] for event in events}
        self.assertIn("STALENESS", categories)
        self.assertIn("CROSS_SOURCE", categories)
        self.assertIn("SPIKE", categories)
        self.assertIn("VOLUME", categories)
        self.assertIn("FUNDING", categories)
        self.assertIn("OPEN_INTEREST", categories)
        self.assertTrue(any(event["blocked"] for event in events))

    def test_build_data_quality_observability_persists_ledger_events(self):
        report = {
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "status": "INVALIDATED",
            "trade_allowed": False,
            "conflict_score": 80,
            "freshness": {
                "candle": {"is_stale": True},
                "feature": {"is_stale": False},
                "regime": {"is_stale": True},
                "orderflow": {"is_stale": False},
                "smc": {"is_stale": False},
            },
            "conflicts": [
                {
                    "name": "feature_regime_mismatch",
                    "severity": "critical",
                    "detail": "Feature trend and regime are pointing in different directions",
                }
            ],
            "funding_rate": 0.002,
            "open_interest_change_pct": 18.0,
            "candle_time": START + timedelta(minutes=2),
        }
        candles = [
            candle(2, 110.0, 300.0),
            candle(1, 100.0, 50.0),
        ]
        db = MagicMock()

        with patch(
            "app.intelligence.data_quality_ledger.build_contradiction_report",
            return_value=report,
        ) as build_report, patch(
            "app.intelligence.data_quality_ledger.get_latest_candles",
            return_value=candles,
        ) as get_candles, patch(
            "app.intelligence.data_quality_ledger.DataQualityEventRepository.record_events",
            return_value=[{"id": 1, "blocked": True}],
        ) as record_events:
            payload = build_data_quality_observability(
                db,
                "BTCUSDT",
                timeframe="5m",
                stale_after_seconds=900,
                limit=20,
                persist=True,
            )

        self.assertTrue(build_report.called)
        self.assertTrue(get_candles.called)
        self.assertTrue(record_events.called)
        self.assertEqual(payload["decision"], "BLOCK")
        self.assertTrue(payload["blocked"])
        self.assertTrue(any("stale" in reason.lower() for reason in payload["blocking_actions"]))


if __name__ == "__main__":
    unittest.main()
