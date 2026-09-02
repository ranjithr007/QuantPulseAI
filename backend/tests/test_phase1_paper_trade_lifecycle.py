import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.paper_trade_api import build_paper_trade_bundle
from app.api.v1.paper_trade_api import execute_paper_trade_candidates_for_symbol
from app.api.v1.paper_trade_api import _official_timeframe_records
from app.api.v1.paper_trade_api import _paper_trade_payload
from app.api.v1.paper_trade_api import _phase2_lifecycle_state
from app.database.models.funding_rates import FundingRate
from app.database.models.market_candles import MarketCandle
from app.database.models.paper_trade import PaperTrade
from app.database.models.point_in_time_snapshots import DecisionSnapshot, FeatureSnapshot
from app.database.models.paper_wallet_ledger import PaperWalletLedgerEntry
from app.database.models.risk_decision import RiskDecision
from app.database.models.trade_plan import TradePlan
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job
from app.repositories.market_participation_repository import MarketParticipationRepository
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.trading.trade_plan_engine import build_trade_plan
from app.strategies.registry import TREND_PULLBACK_DECISION_VERSION
from app.strategies.registry import TREND_PULLBACK_STRATEGY_ID
from app.strategies.registry import TREND_PULLBACK_STRATEGY_VERSION


def _enabled_automation_settings():
    return {
        "enabled": True,
        "locked": False,
        "emergencyStop": False,
        "allowedSymbols": ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"],
        "maxRiskPerTrade": 1.0,
        "dailyLossLimit": 4.0,
        "maxOpenTrades": 4,
        "maxLeverage": 5,
        "maxPositionSize": 170_000.0,
        "minConfidence": 40.0,
        "direction": "BOTH",
        "executionMode": "PAPER",
        "liveExecutionEnabled": False,
    }


def test_open_position_payload_supplies_target2_from_official_exit_policy():
    trade = PaperTrade(
        id=7,
        symbol="XRPUSDT",
        side="LONG",
        entry_price=1.0,
        stop_loss=0.9925,
        target1=1.015,
        target2=None,
        confidence=49.0,
        entry_timeframe="1h",
        status="OPEN",
    )

    payload = _paper_trade_payload(trade)

    assert payload["target2"] == 1.023
    assert payload["exit_policy"] == "PAPER_STAGED_EXIT_V2"
    assert payload["max_hold_hours"] == 48
    assert payload["exit_levels_source"] == "POLICY_FALLBACK"


def test_open_position_payload_labels_capacity_adjusted_sizing():
    trade = PaperTrade(
        id=8,
        symbol="XRPUSDT",
        side="SHORT",
        entry_price=1.0,
        stop_loss=1.0075,
        target1=0.985,
        target2=0.977,
        confidence=49.0,
        entry_timeframe="1h",
        status="OPEN",
        paper_capital_at_entry_inr=200_000,
        allocation_percent=55.0,
        position_notional_inr=110_000,
        leverage=5.0,
        margin_used_inr=22_000,
    )

    payload = _paper_trade_payload(trade)

    assert payload["paper_sizing"]["capacity_adjusted"] is True
    assert payload["paper_sizing"]["position_tier"] == "CAPACITY_ADJUSTED"
    assert payload["paper_sizing"]["requested_position_tier"] == "MINIMUM"
    assert payload["paper_sizing"]["position_notional_inr"] == 110_000
    assert payload["paper_sizing"]["margin_used_inr"] == 22_000


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
            DecisionSnapshot.__table__,
            FeatureSnapshot.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.addCleanup(self.engine.dispose)

    def _seed_bullish_market_participation(self, db, now):
        MarketParticipationRepository().save(
            db,
            {
                "source": "market_participation_trend_v1",
                "symbol": "BTCUSDT",
                "status": "READY",
                "quality_state": "OK",
                "direction": "BULLISH",
                "execution_side": "LONG",
                "score": 62.0,
                "confidence": 62.0,
                "spot": {
                    "status": "READY",
                    "timeframes": [
                        {"timeframe": "1h", "source_timestamp": now},
                    ],
                },
            },
        )

    def _seed_core_fusion_decision(self, db, now, confidence):
        snapshot = DecisionSnapshot(
            symbol="BTCUSDT",
            timeframe="1h",
            source_timestamp=now,
            effective_timestamp=now,
            feature_version="feature_factory_v1",
            decision_version=TREND_PULLBACK_DECISION_VERSION,
            strategy_id=TREND_PULLBACK_STRATEGY_ID,
            strategy_version=TREND_PULLBACK_STRATEGY_VERSION,
            quality_state="OK",
            decision="ELIGIBLE",
            confidence=confidence,
            snapshot_json="{}",
            created_at=now,
        )
        db.add(snapshot)
        db.flush()
        return snapshot

    def test_stop_close_persists_exact_exit_reason(self):
        with self.Session() as db:
            trade = PaperTrade(
                symbol="ETHUSDT",
                side="LONG",
                entry_price=100.0,
                stop_loss=99.25,
                target1=101.5,
                target2=102.3,
                confidence=50.0,
                status="OPEN",
                opened_at=datetime.utcnow() - timedelta(hours=1),
            )
            db.add(trade)
            db.commit()

            closed = PaperTradeRepository().close_trade(
                db,
                trade,
                99.25,
                "LOSS",
                fill_profile={
                    "trigger_type": "STOP",
                    "exit_slippage_pct": 0.0,
                },
            )

            self.assertEqual("STOP", closed.exit_reason)
            self.assertEqual("CLOSED", closed.status)
            self.assertIsNotNone(closed.closed_at)

    def test_policy_upgrade_preserves_an_already_filled_legacy_t1_fraction(self):
        with self.Session() as db:
            trade = PaperTrade(
                symbol="ETHUSDT",
                side="LONG",
                entry_price=100.0,
                stop_loss=100.0,
                target1=101.5,
                target2=102.3,
                confidence=50.0,
                entry_timeframe="1h",
                exit_policy="PAPER_STAGED_EXIT_V1",
                target1_fraction=0.5,
                remaining_position_fraction=0.5,
                target1_hit_at=datetime.utcnow() - timedelta(minutes=10),
                status="OPEN",
                opened_at=datetime.utcnow() - timedelta(hours=1),
            )
            db.add(trade)
            db.commit()

            changed = PaperTradeRepository().ensure_staged_exit_policy(db, trade)

            self.assertTrue(changed)
            self.assertEqual("PAPER_STAGED_EXIT_V2", trade.exit_policy)
            self.assertEqual(0.5, trade.target1_fraction)
            self.assertEqual(0.5, trade.remaining_position_fraction)
            self.assertEqual(100.75, trade.stop_loss)

    def test_candidate_to_fill_to_close_to_pnl(self):
        now = datetime.utcnow().replace(microsecond=0)
        governed = build_trade_plan("LONG", 100.0, 1.0, confidence=80)
        with self.Session() as db:
            snapshot = self._seed_core_fusion_decision(db, now, 80.0)
            plan = TradePlan(
                symbol="BTCUSDT",
                side="LONG",
                entry_price=100.0,
                stop_loss=governed["stop_loss"],
                target1=governed["target1"],
                target2=governed["target2"],
                target3=governed["target3"],
                risk_reward=governed["risk_reward"],
                confidence=80.0,
                mode="intraday",
                entry_timeframe="1h",
                timeframe_stack="1h,4h,1d",
                regime="TRENDING_BULL",
                strategy_id=TREND_PULLBACK_STRATEGY_ID,
                strategy_version=TREND_PULLBACK_STRATEGY_VERSION,
                strategy_decision_snapshot_id=snapshot.id,
                status="OPEN",
                created_at=now - timedelta(minutes=2),
            )
            db.add(plan)
            db.flush()
            db.add(
                RiskDecision(
                    symbol="BTCUSDT",
                    trade_plan_id=plan.id,
                    signal="LONG",
                    decision="APPROVE",
                    entry_price=100.0,
                    stop_loss=governed["stop_loss"],
                    target1=governed["target1"],
                    target2=governed["target2"],
                    risk_reward=governed["risk_reward"],
                    position_size=1.25,
                    risk_percent=1.0,
                    confidence=80.0,
                    strategy_id=TREND_PULLBACK_STRATEGY_ID,
                    strategy_version=TREND_PULLBACK_STRATEGY_VERSION,
                    strategy_decision_snapshot_id=snapshot.id,
                    created_at=now - timedelta(minutes=1),
                )
            )
            self._seed_bullish_market_participation(db, now)
            db.commit()

        with patch("app.api.v1.paper_trade_api.SessionLocal", self.Session), patch(
            "app.api.v1.paper_trade_api.get_automation_settings",
            return_value=object(),
        ), patch(
            "app.api.v1.paper_trade_api.automation_settings_payload",
            return_value=_enabled_automation_settings(),
        ), patch(
            "app.api.v1.paper_trade_api._current_paper_entry_mark",
            return_value={
                "symbol": "BTCUSDT",
                "mark_price": 100.0,
                "observed_at": datetime.now(timezone.utc),
                "source": "TEST_MARK",
            },
        ), patch(
            "app.api.v1.paper_trade_api._current_signal_validation",
            return_value={
                "status": "VALID",
                "trade_allowed": True,
                "signal": "LONG",
                "reasons": [],
            },
        ):
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
            trade = db.query(PaperTrade).filter(PaperTrade.status == "OPEN").one()
            self.assertEqual(170_000, trade.position_notional_inr)
            self.assertEqual(34_000, trade.margin_used_inr)
            self.assertEqual(5, trade.leverage)
            entry_event = db.query(PaperWalletLedgerEntry).one()
            self.assertEqual("ENTRY", entry_event.event_type)
            self.assertEqual(0, entry_event.delta_inr)
            trade.opened_at = now - timedelta(hours=2)
            trade.last_exit_evaluated_at = trade.opened_at
            db.add(
                MarketCandle(
                    id=1,
                    symbol="BTCUSDT",
                    timeframe="5m",
                    open_price=100.5,
                    high_price=112.0,
                    low_price=100.0,
                    close_price=102.5,
                    volume=1000,
                    candle_time=now - timedelta(minutes=10),
                    open_time=now - timedelta(minutes=10),
                    close_time=now - timedelta(minutes=5),
                    is_final=True,
                )
            )
            db.commit()

        with patch("app.jobs.paper_trade_monitor_job.SessionLocal", self.Session):
            first_monitor = run_paper_trade_monitor_job()

        self.assertEqual(1, first_monitor["processed"])
        self.assertEqual(1, first_monitor["policy_updates"])
        self.assertEqual(1, first_monitor["partial_closes"])
        self.assertEqual(0, first_monitor["closed"])

        with self.Session() as db:
            trade = db.query(PaperTrade).filter(PaperTrade.status == "OPEN").one()
            self.assertEqual("PAPER_STAGED_EXIT_V2", trade.exit_policy)
            self.assertEqual(0.25, trade.remaining_position_fraction)
            self.assertEqual(
                round(trade.entry_price + (trade.target1 - trade.entry_price) * 0.5, 2),
                trade.stop_loss,
            )
            db.add(
                MarketCandle(
                    id=2,
                    symbol="BTCUSDT",
                    timeframe="5m",
                    open_price=101.8,
                    high_price=103.0,
                    low_price=101.0,
                    close_price=102.5,
                    volume=1000,
                    candle_time=now - timedelta(minutes=5),
                    open_time=now - timedelta(minutes=5),
                    close_time=now - timedelta(milliseconds=1),
                    is_final=True,
                )
            )
            db.commit()

        with patch("app.jobs.paper_trade_monitor_job.SessionLocal", self.Session):
            second_monitor = run_paper_trade_monitor_job()

        self.assertEqual(1, second_monitor["closed"])
        self.assertEqual(1, second_monitor["wins"])
        self.assertEqual("TARGET2", second_monitor["records"][0]["fill_profile"]["trigger_type"])

        with self.Session() as db:
            trade = db.query(PaperTrade).filter(PaperTrade.status == "CLOSED").one()
            self.assertEqual("TARGET2", trade.exit_reason)
            ledger = (
                db.query(PaperWalletLedgerEntry)
                .order_by(PaperWalletLedgerEntry.id.asc())
                .all()
            )
            self.assertEqual(
                ["ENTRY", "TARGET1_REALIZED", "FINAL_CLOSE_REALIZED"],
                [entry.event_type for entry in ledger],
            )
            self.assertEqual(
                trade.realized_pnl_inr,
                round(sum(entry.delta_inr for entry in ledger), 2),
            )
            bundle = build_paper_trade_bundle(db, symbol="BTCUSDT")

        self.assertEqual(0, bundle["openTrades"]["count"])
        self.assertEqual(1, bundle["closedTrades"]["count"])
        self.assertEqual(1, bundle["summary"]["wins"])
        self.assertEqual(100.0, bundle["performance"]["win_rate"])
        self.assertGreater(bundle["performance"]["total_pnl_percent"], 0)
        self.assertEqual("PERSISTED_LEDGER", bundle["paperWallet"]["accounting_source"])
        self.assertEqual(3, bundle["paperWallet"]["ledger_entry_count"])
        self.assertEqual(
            bundle["closedTrades"]["records"][0]["realized_pnl_inr"],
            bundle["paperWallet"]["realized_pnl_inr"],
        )
        self.assertGreater(bundle["closedTrades"]["records"][0]["fees_percent"], 0)
        self.assertGreater(
            bundle["closedTrades"]["records"][0]["gross_pnl_percent"],
            bundle["closedTrades"]["records"][0]["pnl_percent"],
        )

        # The scanner may produce a new plan while the direction remains LONG.
        # Its planned price can still be the prior setup price, but execution
        # must start from the current mark and derive a completely new bracket.
        decision_time = now + timedelta(seconds=1)
        with self.Session() as db:
            reentry_snapshot = self._seed_core_fusion_decision(
                db,
                decision_time,
                80.0,
            )
            new_plan = TradePlan(
                symbol="BTCUSDT",
                side="LONG",
                entry_price=100.0,
                stop_loss=governed["stop_loss"],
                target1=governed["target1"],
                target2=governed["target2"],
                target3=governed["target3"],
                risk_reward=governed["risk_reward"],
                confidence=80.0,
                mode="intraday",
                entry_timeframe="1h",
                timeframe_stack="1h,4h,1d",
                regime="TRENDING_BULL",
                strategy_id=TREND_PULLBACK_STRATEGY_ID,
                strategy_version=TREND_PULLBACK_STRATEGY_VERSION,
                strategy_decision_snapshot_id=reentry_snapshot.id,
                status="OPEN",
                created_at=decision_time - timedelta(seconds=2),
            )
            db.add(new_plan)
            db.flush()
            db.add(
                RiskDecision(
                    symbol="BTCUSDT",
                    trade_plan_id=new_plan.id,
                    signal="LONG",
                    decision="APPROVE",
                    entry_price=100.0,
                    stop_loss=governed["stop_loss"],
                    target1=governed["target1"],
                    target2=governed["target2"],
                    risk_reward=governed["risk_reward"],
                    position_size=1.25,
                    risk_percent=1.0,
                    confidence=80.0,
                    strategy_id=TREND_PULLBACK_STRATEGY_ID,
                    strategy_version=TREND_PULLBACK_STRATEGY_VERSION,
                    strategy_decision_snapshot_id=reentry_snapshot.id,
                    created_at=decision_time - timedelta(seconds=1),
                )
            )
            db.commit()

        with patch("app.api.v1.paper_trade_api.SessionLocal", self.Session), patch(
            "app.api.v1.paper_trade_api.get_automation_settings",
            return_value=object(),
        ), patch(
            "app.api.v1.paper_trade_api.automation_settings_payload",
            return_value=_enabled_automation_settings(),
        ), patch(
            "app.api.v1.paper_trade_api._current_paper_entry_mark",
            return_value={
                "symbol": "BTCUSDT",
                "mark_price": 110.0,
                "observed_at": datetime.now(timezone.utc),
                "source": "TEST_MARK",
            },
        ), patch(
            "app.api.v1.paper_trade_api._current_signal_validation",
            return_value={
                "status": "VALID",
                "trade_allowed": True,
                "signal": "LONG",
                "reasons": [],
            },
        ):
            reentry = execute_paper_trade_candidates_for_symbol(
                "BTCUSDT",
                stale_after_seconds=900,
            )

        self.assertEqual(1, reentry["executed_count"])
        with self.Session() as db:
            new_trade = db.query(PaperTrade).filter(PaperTrade.status == "OPEN").one()
            self.assertGreater(new_trade.entry_price, 110.0)
            self.assertNotEqual(100.0, new_trade.entry_price)
            self.assertEqual(
                round(new_trade.entry_price * 0.9925, 2),
                new_trade.stop_loss,
            )
            self.assertEqual(
                round(new_trade.entry_price * 1.015, 2),
                new_trade.target1,
            )
            self.assertEqual(
                round(new_trade.entry_price * 1.023, 2),
                new_trade.target2,
            )

    def test_btc_one_hour_trade_scales_out_then_closes_remainder(self):
        now = datetime.utcnow().replace(microsecond=0)
        governed = build_trade_plan(
            "LONG",
            100.0,
            0.3,
            confidence=50,
            symbol="BTCUSDT",
            timeframe="1h",
        )
        with self.Session() as db:
            snapshot = self._seed_core_fusion_decision(db, now, 50.0)
            plan = TradePlan(
                symbol="BTCUSDT",
                side="LONG",
                entry_price=governed["entry"],
                stop_loss=governed["stop_loss"],
                target1=governed["target1"],
                target2=governed["target2"],
                risk_reward=governed["risk_reward"],
                confidence=50.0,
                entry_timeframe="1h",
                exit_policy=governed["exit_policy"],
                target1_fraction=governed["target1_fraction"],
                max_hold_hours=governed["max_hold_hours"],
                strategy_id=TREND_PULLBACK_STRATEGY_ID,
                strategy_version=TREND_PULLBACK_STRATEGY_VERSION,
                strategy_decision_snapshot_id=snapshot.id,
                status="OPEN",
                created_at=now - timedelta(minutes=2),
            )
            db.add(plan)
            db.flush()
            db.add(
                RiskDecision(
                    symbol="BTCUSDT",
                    trade_plan_id=plan.id,
                    signal="LONG",
                    decision="APPROVE",
                    entry_price=governed["entry"],
                    stop_loss=governed["stop_loss"],
                    target1=governed["target1"],
                    target2=governed["target2"],
                    risk_reward=governed["risk_reward"],
                    position_size=1.0,
                    risk_percent=0.5,
                    confidence=50.0,
                    strategy_id=TREND_PULLBACK_STRATEGY_ID,
                    strategy_version=TREND_PULLBACK_STRATEGY_VERSION,
                    strategy_decision_snapshot_id=snapshot.id,
                    created_at=now - timedelta(minutes=1),
                )
            )
            self._seed_bullish_market_participation(db, now)
            db.commit()

        with patch("app.api.v1.paper_trade_api.SessionLocal", self.Session), patch(
            "app.api.v1.paper_trade_api.get_automation_settings",
            return_value=object(),
        ), patch(
            "app.api.v1.paper_trade_api.automation_settings_payload",
            return_value=_enabled_automation_settings(),
        ), patch(
            "app.api.v1.paper_trade_api._current_paper_entry_mark",
            return_value={
                "symbol": "BTCUSDT",
                "mark_price": 100.0,
                "observed_at": datetime.now(timezone.utc),
                "source": "TEST_MARK",
            },
        ), patch(
            "app.api.v1.paper_trade_api._current_signal_validation",
            return_value={
                "status": "VALID",
                "trade_allowed": True,
                "signal": "LONG",
                "reasons": [],
            },
        ):
            execution = execute_paper_trade_candidates_for_symbol(
                "BTCUSDT",
                stale_after_seconds=900,
            )

        self.assertEqual(1, execution["executed_count"])
        self.assertEqual(
            "PAPER_STAGED_EXIT_V2",
            execution["executed"][0]["exit_policy"],
        )

        with self.Session() as db:
            trade = db.query(PaperTrade).filter(PaperTrade.status == "OPEN").one()
            trade.opened_at = now - timedelta(hours=2)
            trade.last_exit_evaluated_at = trade.opened_at
            db.add(
                MarketCandle(
                    id=10,
                    symbol="BTCUSDT",
                    timeframe="5m",
                    open_price=100.5,
                    high_price=101.6,
                    low_price=101.0,
                    close_price=101.2,
                    volume=1000,
                    candle_time=now - timedelta(minutes=10),
                    open_time=now - timedelta(minutes=10),
                    close_time=now - timedelta(minutes=5),
                    is_final=True,
                )
            )
            db.commit()

        with patch("app.jobs.paper_trade_monitor_job.SessionLocal", self.Session):
            first_monitor = run_paper_trade_monitor_job()

        self.assertEqual(1, first_monitor["partial_closes"])
        self.assertEqual(0, first_monitor["closed"])
        with self.Session() as db:
            trade = db.query(PaperTrade).filter(PaperTrade.status == "OPEN").one()
            self.assertIsNotNone(trade.target1_hit_at)
            self.assertIsNotNone(trade.target1_exit_price)
            self.assertEqual(0.25, trade.remaining_position_fraction)
            self.assertEqual(
                round(trade.entry_price + (trade.target1 - trade.entry_price) * 0.5, 2),
                trade.stop_loss,
            )

            db.add(
                MarketCandle(
                    id=11,
                    symbol="BTCUSDT",
                    timeframe="5m",
                    open_price=101.2,
                    high_price=102.5,
                    low_price=101.0,
                    close_price=102.4,
                    volume=1000,
                    candle_time=now - timedelta(minutes=5),
                    open_time=now - timedelta(minutes=5),
                    close_time=now - timedelta(milliseconds=1),
                    is_final=True,
                )
            )
            db.commit()

        with patch("app.jobs.paper_trade_monitor_job.SessionLocal", self.Session):
            second_monitor = run_paper_trade_monitor_job()

        self.assertEqual(1, second_monitor["closed"])
        self.assertEqual(1, second_monitor["wins"])
        self.assertEqual("TARGET2", second_monitor["records"][0]["fill_profile"]["trigger_type"])
        with self.Session() as db:
            trade = db.query(PaperTrade).filter(PaperTrade.status == "CLOSED").one()
            self.assertGreater(trade.gross_pnl_percent, 1.5)
            self.assertGreater(trade.pnl_percent, 1.0)

    def test_existing_altcoin_trade_is_backfilled_to_staged_policy(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.Session() as db:
            plan = TradePlan(
                symbol="SOLUSDT",
                side="LONG",
                entry_price=76.2808,
                stop_loss=72.3615,
                target1=84.7876,
                target2=88.9559,
                risk_reward=2.0,
                confidence=50.0,
                entry_timeframe="4h",
                status="OPEN",
                created_at=now - timedelta(hours=2),
            )
            db.add(plan)
            db.flush()
            db.add(
                PaperTrade(
                    trade_plan_id=plan.id,
                    symbol="SOLUSDT",
                    side="LONG",
                    entry_price=76.2808,
                    stop_loss=72.3615,
                    target1=84.7876,
                    target2=88.9559,
                    confidence=50.0,
                    entry_timeframe="4h",
                    status="OPEN",
                    opened_at=now - timedelta(hours=2),
                )
            )
            db.add(
                MarketCandle(
                    id=20,
                    symbol="SOLUSDT",
                    timeframe="4h",
                    open_price=76.2,
                    high_price=76.5,
                    low_price=76.0,
                    close_price=76.3,
                    volume=1000,
                    candle_time=now,
                    open_time=now - timedelta(hours=4),
                    close_time=now - timedelta(milliseconds=1),
                    is_final=True,
                )
            )
            db.commit()

        with patch("app.jobs.paper_trade_monitor_job.SessionLocal", self.Session):
            monitor = run_paper_trade_monitor_job()

        self.assertEqual(1, monitor["policy_updates"])
        self.assertEqual(1, monitor["still_open"])
        with self.Session() as db:
            trade = db.query(PaperTrade).filter(PaperTrade.status == "OPEN").one()
            self.assertEqual("PAPER_STAGED_EXIT_V2", trade.exit_policy)
            self.assertEqual(75.7087, trade.stop_loss)
            self.assertEqual(77.425, trade.target1)
            self.assertEqual(78.0353, trade.target2)
            self.assertEqual(1.0, trade.remaining_position_fraction)
            self.assertEqual(48, trade.max_hold_hours)

    def test_execution_scope_excludes_legacy_entry_timeframes(self):
        records = [
            TradePlan(symbol="BTCUSDT", side="LONG", entry_timeframe="5m"),
            TradePlan(symbol="DOGEUSDT", side="LONG", entry_timeframe="1h"),
            TradePlan(symbol="ETHUSDT", side="SHORT", entry_timeframe="4h"),
        ]

        filtered = _official_timeframe_records(records)

        self.assertEqual(["DOGEUSDT", "ETHUSDT"], [item.symbol for item in filtered])

    def test_account_wide_bundle_can_return_the_complete_trade_ledger(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.Session() as db:
            db.add_all(
                [
                    PaperTrade(
                        symbol=f"COIN{index}USDT",
                        side="LONG",
                        entry_price=100.0,
                        status="CLOSED",
                        entry_timeframe="1h",
                        pnl_percent=float(index),
                        closed_at=now + timedelta(seconds=index),
                        created_at=now + timedelta(seconds=index),
                    )
                    for index in range(15)
                ]
            )
            db.commit()

            capped = build_paper_trade_bundle(db, closed_limit=12)
            complete = build_paper_trade_bundle(db, closed_limit=None)

        self.assertEqual(15, capped["closedTrades"]["count"])
        self.assertEqual(12, capped["closedTrades"]["records_returned"])
        self.assertTrue(capped["closedTrades"]["has_more"])
        self.assertEqual(15, complete["closedTrades"]["count"])
        self.assertEqual(15, complete["closedTrades"]["records_returned"])
        self.assertFalse(complete["closedTrades"]["has_more"])

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
