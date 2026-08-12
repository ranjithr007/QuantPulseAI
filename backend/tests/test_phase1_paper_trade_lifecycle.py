import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.paper_trade_api import build_paper_trade_bundle
from app.api.v1.paper_trade_api import execute_paper_trade_candidates_for_symbol
from app.api.v1.paper_trade_api import _official_timeframe_records
from app.api.v1.paper_trade_api import _phase2_lifecycle_state
from app.database.models.funding_rates import FundingRate
from app.database.models.market_candles import MarketCandle
from app.database.models.paper_trade import PaperTrade
from app.database.models.risk_decision import RiskDecision
from app.database.models.trade_plan import TradePlan
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job


class Phase1PaperTradeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        for table in (
            TradePlan.__table__,
            RiskDecision.__table__,
            PaperTrade.__table__,
            MarketCandle.__table__,
            FundingRate.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.addCleanup(self.engine.dispose)

    def test_candidate_to_fill_to_close_to_pnl(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.Session() as db:
            plan = TradePlan(
                symbol="BTCUSDT",
                side="LONG",
                entry_price=100.0,
                stop_loss=99.0,
                target1=102.0,
                target2=103.0,
                target3=104.0,
                risk_reward=2.0,
                confidence=80.0,
                mode="intraday",
                entry_timeframe="1h",
                timeframe_stack="1h,4h,1d",
                regime="TRENDING_BULL",
                status="OPEN",
                created_at=now - timedelta(minutes=2),
            )
            db.add(plan)
            db.flush()
            db.add(
                RiskDecision(
                    symbol="BTCUSDT",
                    signal="LONG",
                    decision="APPROVE",
                    entry_price=100.0,
                    stop_loss=99.0,
                    target1=102.0,
                    target2=103.0,
                    risk_reward=2.0,
                    position_size=1.25,
                    risk_percent=1.0,
                    confidence=80.0,
                    created_at=now - timedelta(minutes=1),
                )
            )
            db.commit()

        with patch("app.api.v1.paper_trade_api.SessionLocal", self.Session):
            execution = execute_paper_trade_candidates_for_symbol("BTCUSDT", stale_after_seconds=900)
            duplicate = execute_paper_trade_candidates_for_symbol("BTCUSDT", stale_after_seconds=900)

        self.assertEqual(1, execution["candidate_count"])
        self.assertEqual(1, execution["executed_count"])
        self.assertGreater(execution["executed"][0]["entry_price"], 100.0)
        self.assertEqual("intraday", execution["executed"][0]["mode"])
        self.assertEqual("1h", execution["executed"][0]["entry_timeframe"])
        self.assertEqual("TRENDING_BULL", execution["executed"][0]["regime"])
        self.assertEqual("paper_trade_fill_model_v1", execution["executed"][0]["fill_profile"]["model"])
        self.assertEqual(0, duplicate["executed_count"])
        self.assertEqual("skipped_existing_open_paper_trade", duplicate["skipped"][0]["action"])

        with self.Session() as db:
            db.add(
                MarketCandle(
                    id=1,
                    symbol="BTCUSDT",
                    timeframe="1h",
                    open_price=100.5,
                    high_price=103.0,
                    low_price=100.0,
                    close_price=102.5,
                    volume=1000,
                    candle_time=now,
                    open_time=now - timedelta(hours=1),
                    close_time=now - timedelta(milliseconds=1),
                    is_final=True,
                )
            )
            db.commit()

        with patch("app.jobs.paper_trade_monitor_job.SessionLocal", self.Session):
            monitor = run_paper_trade_monitor_job()

        self.assertEqual(1, monitor["processed"])
        self.assertEqual(1, monitor["closed"])
        self.assertEqual(1, monitor["wins"])
        self.assertEqual("TARGET", monitor["records"][0]["fill_profile"]["trigger_type"])

        with self.Session() as db:
            bundle = build_paper_trade_bundle(db, symbol="BTCUSDT")

        self.assertEqual(0, bundle["openTrades"]["count"])
        self.assertEqual(1, bundle["closedTrades"]["count"])
        self.assertEqual(1, bundle["summary"]["wins"])
        self.assertEqual(100.0, bundle["performance"]["win_rate"])
        self.assertGreater(bundle["performance"]["total_pnl_percent"], 0)
        self.assertGreater(bundle["closedTrades"]["records"][0]["fees_percent"], 0)
        self.assertGreater(
            bundle["closedTrades"]["records"][0]["gross_pnl_percent"],
            bundle["closedTrades"]["records"][0]["pnl_percent"],
        )

    def test_execution_scope_excludes_legacy_entry_timeframes(self):
        records = [
            TradePlan(symbol="BTCUSDT", side="LONG", entry_timeframe="5m"),
            TradePlan(symbol="DOGEUSDT", side="LONG", entry_timeframe="1h"),
            TradePlan(symbol="ETHUSDT", side="SHORT", entry_timeframe="4h"),
        ]

        filtered = _official_timeframe_records(records)

        self.assertEqual(["DOGEUSDT", "ETHUSDT"], [item.symbol for item in filtered])

    def test_lifecycle_funnel_waits_without_manufacturing_a_trade(self):
        status, next_action = _phase2_lifecycle_state(
            {
                "ready_count": 0,
                "coverage": {"status": "COMPLETE"},
            },
            plans=[],
            approved_candidates=[],
            eligible_candidates=[],
            open_trades=[],
        )

        self.assertEqual("WAITING_FOR_READY", status)
        self.assertIn("1h/2h/4h/1d", next_action)

    def test_lifecycle_funnel_does_not_queue_historical_ready_evidence(self):
        status, next_action = _phase2_lifecycle_state(
            {
                "ready_count": 3,
                "actionable_ready_count": 0,
                "coverage": {"status": "COMPLETE"},
            },
            plans=[],
            approved_candidates=[],
            eligible_candidates=[],
            open_trades=[],
        )

        self.assertEqual("WAITING_FOR_READY", status)
        self.assertIn("scheduled", next_action)

    def test_lifecycle_funnel_queues_only_current_ready_evidence(self):
        status, next_action = _phase2_lifecycle_state(
            {
                "ready_count": 3,
                "actionable_ready_count": 1,
                "coverage": {"status": "COMPLETE"},
            },
            plans=[],
            approved_candidates=[],
            eligible_candidates=[],
            open_trades=[],
        )

        self.assertEqual("QUEUE_PENDING", status)
        self.assertIn("live READY", next_action)


if __name__ == "__main__":
    unittest.main()
