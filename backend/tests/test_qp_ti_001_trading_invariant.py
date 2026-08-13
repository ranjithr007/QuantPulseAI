from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.v1 import paper_trade_api
from app.api.v1 import risk_api
from app.api.v1.signals_api import _market_direction
from app.api.v1.signals_api import _watchlist_computed_risk_payload
from app.api.v1.signals_api import _watchlist_row
from app.database.models.fusion_signal import FusionSignal
from app.database.models.paper_trade import PaperTrade
from app.database.models.funding_rates import FundingRate
from app.database.models.trade_plan import TradePlan
from app.governance.evidence_policy import FULL_SIZE_ENTRY_CONFIDENCE
from app.governance.evidence_policy import MINIMUM_TIER_RISK_PERCENT
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.intelligence.master_ai_engine import _signal_from_score
from app.risk.confidence_sizing import confidence_sizing_profile
from app.intelligence.multi_timeframe_engine import combine_timeframe_signals
from app.jobs.deterministic_pipeline_job import STAGE_ORDER
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.fusion_signal_repository import FusionSignalRepository


def _candidate(plan_id, timeframe, confidence, *, side="LONG", risk_reward=2.0):
    return {
        "symbol": "BTCUSDT",
        "side": side,
        "eligible": True,
        "blocked_reasons": [],
        "trade_plan": {
            "id": plan_id,
            "entry_timeframe": timeframe,
            "confidence": confidence,
            "risk_reward": risk_reward,
            "created_at": datetime(2026, 8, 11, plan_id, tzinfo=timezone.utc),
        },
        "risk_decision": {"confidence": confidence},
    }


def test_governed_stack_contains_all_four_required_timeframes():
    assert OFFICIAL_ENTRY_TIMEFRAMES == ("1h", "2h", "4h", "1d")


def test_governed_score_and_position_tier_boundaries():
    assert MIN_ENTRY_CONFIDENCE == 40.0
    assert FULL_SIZE_ENTRY_CONFIDENCE == 60.0
    assert MINIMUM_TIER_RISK_PERCENT == 0.5
    assert _signal_from_score(39.99) == "WAIT"
    assert _signal_from_score(40) == "LONG"
    assert _signal_from_score(-39.99) == "WAIT"
    assert _signal_from_score(-40) == "SHORT"
    assert confidence_sizing_profile(59.99, 1.0) == {
        "position_tier": "MINIMUM",
        "risk_percent": 0.5,
        "requested_risk_percent": 1.0,
    }
    assert confidence_sizing_profile(60, 1.0)["position_tier"] == "MAXIMUM"
    assert risk_api._normalize_auto_settings({"minConfidence": 70})["minConfidence"] == 40


def test_selected_timeframe_confidence_drives_watchlist_and_risk():
    payload = {
        "symbol": "XRPUSDT",
        "timeframes_used": list(OFFICIAL_ENTRY_TIMEFRAMES),
        "timeframes": [
            {"timeframe": "1h", "confidence": 0, "score": 0, "bias": "NEUTRAL"},
            {"timeframe": "2h", "confidence": 0, "score": 0, "bias": "NEUTRAL"},
            {"timeframe": "4h", "confidence": 49, "score": -49, "bias": "SHORT"},
            {"timeframe": "1d", "confidence": 0, "score": 0, "bias": "NEUTRAL"},
        ],
        "trigger": {
            "status": "READY",
            "side": "SHORT",
            "reason": "4h SHORT entry trigger is ready",
            "entry_timeframe": "4h",
            "conditions": [],
        },
        "confirmation": {
            "overall_bias": "BEARISH_ALIGNMENT",
            "trade_permission": "SHORT_ALLOWED",
        },
        "trade_plan": {
            "entry": 100,
            "stop_loss": 101,
            "target1": 98,
            "target2": 97,
            "risk_reward": 2.0,
        },
        "trade_plan_validation": {"is_valid": True, "errors": []},
    }

    computed_risk = _watchlist_computed_risk_payload(payload)
    row = _watchlist_row(payload)

    assert computed_risk["decision"] == "APPROVE"
    assert computed_risk["confidence"] == 49
    assert computed_risk["position_tier"] == "MINIMUM"
    assert computed_risk["risk_percent"] == 0.5
    assert row["entry_timeframe"] == "4h"
    assert row["entry_score"] == -49
    assert row["confidence"] == 49


def test_legacy_fusion_repository_uses_governed_40_percent_floor():
    engine = create_engine("sqlite:///:memory:")
    FusionSignal.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add_all(
            [
                FusionSignal(symbol="LOW", decision="LONG", confidence=39.99, timeframe="1h"),
                FusionSignal(symbol="MIN", decision="LONG", confidence=40, timeframe="2h"),
                FusionSignal(symbol="SHORT", decision="SHORT", confidence=49, timeframe="4h"),
                FusionSignal(symbol="WAIT", decision="WAIT", confidence=90, timeframe="1d"),
            ]
        )
        session.commit()

        results = FusionSignalRepository().get_latest_tradeable_signals(session)

        assert {item.symbol for item in results} == {"MIN", "SHORT"}
    finally:
        session.close()


def test_four_timeframe_direction_requires_full_stack_alignment():
    timeframes = [
        {"timeframe": timeframe, "bias": "LONG", "signal": "LONG"}
        for timeframe in OFFICIAL_ENTRY_TIMEFRAMES
    ]

    result = combine_timeframe_signals(timeframes)

    assert result["overall_bias"] == "BULLISH_ALIGNMENT"
    assert result["trade_permission"] == "LONG_ALLOWED"


@pytest.mark.parametrize(
    ("bias", "signal", "expected"),
    [
        ("LONG", "LONG", "BULLISH"),
        ("WEAK_SHORT", "WAIT", "BEARISH"),
        ("NEUTRAL", "WAIT", "NEUTRAL"),
    ],
)
def test_each_timeframe_exposes_canonical_market_direction(bias, signal, expected):
    assert _market_direction(bias, signal) == expected


def test_executor_selects_only_strongest_eligible_candidate_per_symbol(monkeypatch):
    candidates = [
        _candidate(1, "1h", 72),
        _candidate(2, "4h", 81),
        _candidate(3, "1d", 81, risk_reward=2.5),
    ]
    saved = []

    class DummyDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeRepo:
        def has_open_trade(self, db, symbol, side=None):
            return False

        def has_trade_for_plan(self, db, trade_plan_id):
            return False

        def save_candidate(self, db, candidate):
            saved.append(candidate)
            return SimpleNamespace(id=99)

    monkeypatch.setattr(paper_trade_api, "SessionLocal", DummyDb)
    monkeypatch.setattr(
        paper_trade_api,
        "build_paper_trade_candidates",
        lambda *args, **kwargs: (None, candidates),
    )
    monkeypatch.setattr(paper_trade_api, "PaperTradeRepository", FakeRepo)
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_trade_payload",
        lambda trade, fill_profile=None: {"id": trade.id},
    )

    result = paper_trade_api.execute_paper_trade_candidates_for_symbol()

    assert [item["trade_plan"]["id"] for item in saved] == [3]
    assert result["executed_count"] == 1
    assert sum(
        item["action"] == "skipped_weaker_symbol_candidate"
        for item in result["skipped"]
    ) == 2


def test_symbol_lock_blocks_opposite_direction_and_database_duplicate():
    engine = create_engine("sqlite:///:memory:")
    PaperTrade.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_paper_trades_one_open_symbol "
                "ON paper_trades(symbol) WHERE status = 'OPEN'"
            )
        )
    session = sessionmaker(bind=engine)()
    try:
        session.add(PaperTrade(symbol="BTCUSDT", side="LONG", status="OPEN"))
        session.commit()

        assert PaperTradeRepository().has_open_trade(session, "BTCUSDT", "SHORT")

        session.add(PaperTrade(symbol="BTCUSDT", side="SHORT", status="OPEN"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(PaperTrade(symbol="ETHUSDT", side="SHORT", status="OPEN"))
        session.commit()
    finally:
        session.close()


def test_monitoring_precedes_recalculation_and_execution():
    order = [name for name, _ in STAGE_ORDER]

    assert order == [
        "market",
        "paper_trade_monitor",
        "feature",
        "regime",
        "orderflow",
        "smc",
        "fusion",
        "watchlist_persist",
        "risk",
        "paper_trade_execute",
    ]


def test_trade_close_releases_lock_and_invalidates_all_queued_symbol_plans():
    engine = create_engine("sqlite:///:memory:")
    TradePlan.__table__.create(engine)
    PaperTrade.__table__.create(engine)
    FundingRate.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        active_plan = TradePlan(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=100,
            stop_loss=99,
            target1=102,
            status="OPEN",
        )
        queued_plan = TradePlan(
            symbol="BTCUSDT",
            side="SHORT",
            entry_price=100,
            stop_loss=101,
            target1=98,
            status="OPEN",
        )
        session.add_all([active_plan, queued_plan])
        session.flush()
        trade = PaperTrade(
            trade_plan_id=active_plan.id,
            symbol="BTCUSDT",
            side="LONG",
            entry_price=100,
            stop_loss=99,
            target1=102,
            fee_bps=0,
            status="OPEN",
        )
        session.add(trade)
        session.commit()

        PaperTradeRepository().close_trade(session, trade, 102, "WIN")

        assert trade.status == "CLOSED"
        assert PaperTradeRepository().has_open_trade(session, "BTCUSDT") is False
        plans = session.query(TradePlan).order_by(TradePlan.id).all()
        assert [plan.status for plan in plans] == ["CLOSED", "CLOSED"]
        assert plans[0].result == "WIN"
        assert plans[1].result == "STALE_AFTER_CLOSE"
    finally:
        session.close()
