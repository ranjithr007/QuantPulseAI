from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import notification_api
from app.database.models.app_notification import AppNotification
from app.database.sqlserver import Base
from app.repositories.notification_repository import NotificationRepository
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.automation_settings_repository import get_automation_settings
from app.repositories.automation_settings_repository import set_emergency_stop


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _paper_candidate():
    return {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "trade_plan": {
            "id": 101,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "entry_price": 100.0,
            "stop_loss": 99.25,
            "target1": 101.5,
            "target2": 102.3,
            "confidence": 64.0,
            "risk_reward": 2.0,
            "entry_timeframe": "1h",
            "timeframe_stack": "1h,2h,4h,1d",
            "strategy_id": "CORE_FUSION",
            "strategy_version": "1.0.0",
            "strategy_decision_snapshot_id": 301,
        },
        "risk_decision": {
            "id": 201,
            "entry_price": 100.0,
            "stop_loss": 99.25,
            "target1": 101.5,
            "target2": 102.3,
            "position_size": 1.0,
            "risk_reward": 2.0,
            "risk_percent": 1.0,
            "confidence": 64.0,
            "strategy_id": "CORE_FUSION",
            "strategy_version": "1.0.0",
            "strategy_decision_snapshot_id": 301,
        },
        "market_context": {},
        "fill_profile": {
            "entry_fill_price": 100.0,
            "planned_entry_price": 100.0,
            "fee_bps": 7.5,
            "model": "notification-test-v1",
        },
    }


def test_repository_deduplicates_and_tracks_read_state():
    factory = _session_factory()
    db = factory()
    try:
        repo = NotificationRepository()
        first, created = repo.create(
            db,
            event_key="event:1",
            category="SYSTEM",
            event_type="TEST",
            severity="INFO",
            title="Test",
            message="Test notification",
            commit=True,
        )
        duplicate, duplicate_created = repo.create(
            db,
            event_key="event:1",
            category="SYSTEM",
            event_type="TEST",
            severity="INFO",
            title="Test",
            message="Test notification",
            commit=True,
        )

        assert created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert repo.unread_count(db) == 1
        repo.mark_read(db, first.id)
        assert repo.unread_count(db) == 0
        assert db.query(AppNotification).count() == 1
    finally:
        db.close()


def test_official_trade_lifecycle_emits_notifications_without_duplicates():
    factory = _session_factory()
    db = factory()
    try:
        repo = PaperTradeRepository()
        trade = repo.save_candidate(db, _paper_candidate())
        assert [row.event_type for row in NotificationRepository().list(db)] == [
            "PAPER_TRADE_OPENED"
        ]

        trade = repo.apply_target1(
            db,
            trade,
            trade.target1,
            candle_time=datetime.utcnow(),
        )
        moved_stop = float(trade.stop_loss) + 0.1
        trade = repo.move_stop_loss(db, trade, moved_stop)
        trade = repo.close_trade(
            db,
            trade,
            trade.target2,
            "WIN",
            fill_profile={"trigger_type": "TARGET2", "exit_slippage_pct": 0.0},
        )

        event_types = {
            row.event_type for row in NotificationRepository().list(db)
        }
        assert event_types == {
            "PAPER_TRADE_OPENED",
            "TARGET1_REACHED",
            "PROTECTIVE_STOP_MOVED",
            "TARGET2_REACHED",
        }
        assert db.query(AppNotification).count() == 4
        assert all(row.paper_trade_id == trade.id for row in db.query(AppNotification))
    finally:
        db.close()


def test_notification_api_lists_and_marks_all_read():
    factory = _session_factory()
    db = factory()
    NotificationRepository().create(
        db,
        event_key="api:event:1",
        category="RISK",
        event_type="TEST",
        severity="WARNING",
        title="API test",
        message="Unread",
        commit=True,
    )
    db.close()

    with patch.object(notification_api, "SessionLocal", side_effect=factory):
        listed = notification_api.list_notifications(unread_only=False, limit=50)
        marked = notification_api.mark_all_notifications_read()
        unread = notification_api.notification_unread_count()

    assert listed["count"] == 1
    assert listed["unreadCount"] == 1
    assert listed["records"][0]["isRead"] is False
    assert marked["updatedCount"] == 1
    assert unread["unreadCount"] == 0


def test_emergency_stop_emits_one_risk_notification_per_state_change():
    factory = _session_factory()
    db = factory()
    try:
        get_automation_settings(db)
        _settings, activated = set_emergency_stop(db, True, actor="test")
        _settings, duplicate = set_emergency_stop(db, True, actor="test")
        _settings, cleared = set_emergency_stop(db, False, actor="test")

        rows = NotificationRepository().list(db)
        assert activated is True
        assert duplicate is False
        assert cleared is True
        assert [row.event_type for row in rows] == [
            "EMERGENCY_STOP_CLEARED",
            "EMERGENCY_STOP_ACTIVATED",
        ]
    finally:
        db.close()
