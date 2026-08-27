import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import strategy_api
from app.api.v1.paper_trade_api import _paper_trade_blocked_reasons
from app.api.v1.paper_trade_api import _risk_decision_payload
from app.api.v1.paper_trade_api import _trade_plan_payload
from app.api.v1.signals_api import CORE_FUSION_DECISION_VERSION
from app.api.v1.signals_api import _persist_core_fusion_strategy_snapshot
from app.database.models.paper_trade import PaperTrade
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.risk_decision import RiskDecision
from app.database.sqlserver import Base
from app.paper_trading.fill_model import build_fill_profile
from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.risk_repository import RiskRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.strategies.registry import CORE_FUSION_STRATEGY_ID
from app.strategies.registry import CORE_FUSION_STRATEGY_VERSION


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _eligible_payload(now):
    return {
        "symbol": "BTCUSDT",
        "mode": "intraday",
        "timeframes_used": ["1h", "2h", "4h", "1d"],
        "timeframes": [
            {
                "timeframe": "1h",
                "candle_time": now,
                "status": "OK",
                "score": 52.0,
                "confidence": 52.0,
                "component_scores": {"regime": {"value": "TRENDING_BULL"}},
            }
        ],
        "confirmation": {},
        "trigger": {
            "status": "READY",
            "side": "LONG",
            "reason": "Core Fusion signal passed",
            "conditions": [],
        },
        "trade_plan": {
            "entry": 100.0,
            "stop_loss": 99.25,
            "target1": 101.5,
            "target2": 102.3,
            "risk_reward": 2.1,
        },
        "trade_plan_validation": {"is_valid": True, "errors": []},
    }


def _bullish_participation(now):
    return {
        "status": "READY",
        "quality_state": "OK",
        "direction": "BULLISH",
        "score": 61.0,
        "confidence": 61.0,
        "effective_timestamp": now,
        "data_generation_id": "generation-1",
    }


def test_core_fusion_attribution_survives_snapshot_plan_risk_and_paper_trade():
    Session = _session_factory()
    db = Session()
    now = datetime.utcnow().replace(microsecond=0)

    snapshot = _persist_core_fusion_strategy_snapshot(
        db,
        _eligible_payload(now),
        _bullish_participation(now),
    )
    assert snapshot["decision"] == "ELIGIBLE"
    record = db.query(DecisionSnapshot).filter(DecisionSnapshot.id == snapshot["id"]).one()
    assert record.decision_version == CORE_FUSION_DECISION_VERSION
    assert record.strategy_id == CORE_FUSION_STRATEGY_ID
    assert record.strategy_version == CORE_FUSION_STRATEGY_VERSION

    plan = TradePlanRepository().save_ready_trade_plan(
        db,
        "BTCUSDT",
        "LONG",
        _eligible_payload(now)["trade_plan"],
        52.0,
        context={
            "mode": "intraday",
            "entry_timeframe": "1h",
            "timeframe_stack": ["1h", "2h", "4h", "1d"],
            "regime": "TRENDING_BULL",
            "strategy_id": CORE_FUSION_STRATEGY_ID,
            "strategy_version": CORE_FUSION_STRATEGY_VERSION,
            "strategy_decision_snapshot_id": snapshot["id"],
        },
    )
    assert plan.strategy_decision_snapshot_id == snapshot["id"]

    risk_id = RiskRepository().save(
        {
            "symbol": "BTCUSDT",
            "signal": "LONG",
            "decision": "APPROVE",
            "entry": plan.entry_price,
            "stop_loss": plan.stop_loss,
            "targets": {"t1": plan.target1, "t2": plan.target2},
            "position_size": 1.0,
            "risk_reward": 2.1,
            "confidence": 52.0,
            "risk_percent": 0.5,
            "decision_type": "TRADE_PLAN_APPROVAL",
            "trade_plan_id": plan.id,
            "thesis_id": plan.thesis_id,
            "timeframe": "1h",
            "strategy_id": plan.strategy_id,
            "strategy_version": plan.strategy_version,
            "strategy_decision_snapshot_id": plan.strategy_decision_snapshot_id,
        },
        db=db,
    )
    risk = db.query(RiskDecision).filter(RiskDecision.id == risk_id).one()
    assert risk.strategy_id == plan.strategy_id
    assert risk.strategy_decision_snapshot_id == plan.strategy_decision_snapshot_id

    risk_payload = _risk_decision_payload(risk, 900)
    plan_payload = _trade_plan_payload(plan)
    fill = build_fill_profile(
        side="LONG",
        planned_entry_price=plan.entry_price,
        stop_loss=plan.stop_loss,
        target1=plan.target2,
        confidence=52.0,
        risk_reward=2.1,
    )
    trade = PaperTradeRepository().save_candidate(
        db,
        {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "trade_plan": plan_payload,
            "risk_decision": risk_payload,
            "execution_risk": risk_payload,
            "fill_profile": fill,
            "paper_sizing": build_inr_paper_sizing(52.0),
            "market_context": {},
            "validation_contract_version": "test-contract",
        },
    )
    assert trade.strategy_id == CORE_FUSION_STRATEGY_ID
    assert trade.strategy_version == CORE_FUSION_STRATEGY_VERSION
    assert trade.strategy_decision_snapshot_id == snapshot["id"]
    db.close()


def test_mismatched_strategy_risk_cannot_authorize_paper_trade():
    now = datetime.utcnow()
    trade = SimpleNamespace(
        id=7,
        side="LONG",
        entry_price=100.0,
        stop_loss=99.25,
        target1=101.5,
        created_at=now,
        strategy_id=CORE_FUSION_STRATEGY_ID,
        strategy_version=CORE_FUSION_STRATEGY_VERSION,
        strategy_decision_snapshot_id=10,
    )
    risk = SimpleNamespace(
        trade_plan_id=8,
        decision="APPROVE",
        signal="LONG",
        entry_price=100.0,
        stop_loss=99.25,
        target1=101.5,
        created_at=now + timedelta(seconds=1),
        strategy_id="OTHER_STRATEGY",
        strategy_version="other_v1",
        strategy_decision_snapshot_id=99,
    )
    reasons = _paper_trade_blocked_reasons(
        trade,
        risk,
        {"freshness": {"is_stale": False}},
        fill_profile={"effective_risk_reward": 2.1},
    )
    assert "Risk strategy does not match trade plan" in reasons
    assert "Risk strategy version does not match trade plan" in reasons
    assert "Risk strategy decision snapshot does not match trade plan" in reasons
    assert "Risk decision does not match the exact trade plan" in reasons


def test_unversioned_or_legacy_plan_cannot_reach_paper_execution():
    now = datetime.utcnow()
    trade = SimpleNamespace(
        id=7,
        side="LONG",
        entry_price=100.0,
        stop_loss=99.25,
        target1=101.5,
        created_at=now,
        strategy_id="LEGACY_UNATTRIBUTED",
        strategy_version="pre_strategy_lineage_v0",
        strategy_decision_snapshot_id=None,
    )
    risk = SimpleNamespace(
        trade_plan_id=7,
        decision="APPROVE",
        signal="LONG",
        entry_price=100.0,
        stop_loss=99.25,
        target1=101.5,
        created_at=now,
        strategy_id=trade.strategy_id,
        strategy_version=trade.strategy_version,
        strategy_decision_snapshot_id=None,
    )

    reasons = _paper_trade_blocked_reasons(
        trade,
        risk,
        {"freshness": {"is_stale": False}},
        fill_profile={"effective_risk_reward": 2.1},
    )

    assert "Trade plan strategy is not enabled for paper execution" in reasons
    assert "Trade plan has no strategy decision snapshot" in reasons


def test_active_core_fusion_lineage_passes_strategy_execution_boundary():
    now = datetime.utcnow()
    shared = {
        "strategy_id": CORE_FUSION_STRATEGY_ID,
        "strategy_version": CORE_FUSION_STRATEGY_VERSION,
        "strategy_decision_snapshot_id": 42,
    }
    trade = SimpleNamespace(
        id=7,
        symbol="BTCUSDT",
        entry_timeframe="1h",
        side="SHORT",
        entry_price=100.0,
        stop_loss=100.75,
        target1=98.5,
        created_at=now,
        **shared,
    )
    risk = SimpleNamespace(
        trade_plan_id=7,
        decision="APPROVE",
        signal="SHORT",
        entry_price=100.0,
        stop_loss=100.75,
        target1=98.5,
        created_at=now,
        **shared,
    )

    reasons = _paper_trade_blocked_reasons(
        trade,
        risk,
        {"freshness": {"is_stale": False}},
        fill_profile={"effective_risk_reward": 2.1},
        strategy_snapshot=SimpleNamespace(
            id=42,
            symbol="BTCUSDT",
            timeframe="1h",
            decision="ELIGIBLE",
            decision_version=CORE_FUSION_DECISION_VERSION,
            strategy_id=CORE_FUSION_STRATEGY_ID,
            strategy_version=CORE_FUSION_STRATEGY_VERSION,
        ),
    )

    assert reasons == []


def test_strategy_summary_excludes_other_strategy_version(monkeypatch):
    Session = _session_factory()
    db = Session()
    now = datetime.utcnow().replace(microsecond=0)
    db.add_all(
        [
            DecisionSnapshot(
                symbol="BTCUSDT",
                timeframe="1h",
                source_timestamp=now,
                effective_timestamp=now,
                feature_version="feature_factory_v1",
                decision_version=CORE_FUSION_DECISION_VERSION,
                strategy_id=CORE_FUSION_STRATEGY_ID,
                strategy_version=CORE_FUSION_STRATEGY_VERSION,
                quality_state="OK",
                decision="ELIGIBLE",
                confidence=55.0,
                snapshot_json='{"context":{"side":"LONG","selected_score":55}}',
                created_at=now,
            ),
            DecisionSnapshot(
                symbol="ETHUSDT",
                timeframe="1h",
                source_timestamp=now,
                effective_timestamp=now,
                feature_version="feature_factory_v1",
                decision_version=CORE_FUSION_DECISION_VERSION,
                strategy_id=CORE_FUSION_STRATEGY_ID,
                strategy_version="core_fusion_v2",
                quality_state="OK",
                decision="ELIGIBLE",
                confidence=90.0,
                snapshot_json="{}",
                created_at=now,
            ),
            PaperTrade(
                symbol="BTCUSDT",
                side="LONG",
                entry_timeframe="1h",
                strategy_id=CORE_FUSION_STRATEGY_ID,
                strategy_version=CORE_FUSION_STRATEGY_VERSION,
                status="CLOSED",
                result="WIN",
                pnl_percent=1.0,
                realized_pnl_inr=1500.0,
                created_at=now,
                closed_at=now,
            ),
            PaperTrade(
                symbol="ETHUSDT",
                side="LONG",
                entry_timeframe="1h",
                strategy_id=CORE_FUSION_STRATEGY_ID,
                strategy_version="core_fusion_v2",
                status="CLOSED",
                result="WIN",
                pnl_percent=99.0,
                realized_pnl_inr=99999.0,
                created_at=now,
                closed_at=now,
            ),
        ]
    )
    db.commit()
    db.close()
    monkeypatch.setattr(strategy_api, "SessionLocal", Session)

    payload = strategy_api.get_strategy_summary(
        strategy_id=None,
        since_days=30,
        candidate_limit=24,
    )
    record = next(
        item
        for item in payload["records"]
        if item["id"] == CORE_FUSION_STRATEGY_ID
    )
    assert record["coverage"]["decision_snapshots"] == 1
    assert record["performance"]["total_trades"] == 0
    assert record["official_performance"]["total_trades"] == 1
    assert record["official_performance"]["net_pnl_inr"] == 1500.0
    assert [item["symbol"] for item in record["candidates"]] == ["BTCUSDT"]


def test_latest_unchanged_snapshot_reuses_matching_open_position_lifecycle():
    now = datetime.utcnow()
    latest_snapshot = SimpleNamespace(
        id=200,
        symbol="BTCUSDT",
        timeframe="1h",
        confidence=64.0,
        decision="ELIGIBLE",
        snapshot_json=json.dumps(
            {
                "context": {
                    "side": "LONG",
                    "selected_score": 64.0,
                    "market_participation": {},
                    "blocked_reasons": [],
                }
            }
        ),
        effective_timestamp=now,
        created_at=now,
    )
    older_plan = SimpleNamespace(
        id=10,
        strategy_decision_snapshot_id=100,
        symbol="BTCUSDT",
        side="LONG",
        entry_timeframe="1h",
        status="OPEN",
    )
    open_trade = SimpleNamespace(
        id=20,
        strategy_decision_snapshot_id=100,
        symbol="BTCUSDT",
        side="LONG",
        entry_timeframe="1h",
        status="OPEN",
    )

    records = strategy_api._latest_candidates(
        [latest_snapshot],
        [older_plan],
        [open_trade],
        [],
        24,
    )

    assert records[0]["trade_plan_id"] == 10
    assert records[0]["paper_trade_id"] == 20
    assert records[0]["lifecycle"] == "POSITION_OPEN"


def test_latest_snapshot_does_not_reuse_opposite_side_open_position():
    now = datetime.utcnow()
    latest_snapshot = SimpleNamespace(
        id=201,
        symbol="BTCUSDT",
        timeframe="1h",
        confidence=64.0,
        decision="ELIGIBLE",
        snapshot_json=json.dumps(
            {
                "context": {
                    "side": "SHORT",
                    "selected_score": -64.0,
                    "market_participation": {},
                    "blocked_reasons": [],
                }
            }
        ),
        effective_timestamp=now,
        created_at=now,
    )
    long_trade = SimpleNamespace(
        id=21,
        strategy_decision_snapshot_id=100,
        symbol="BTCUSDT",
        side="LONG",
        entry_timeframe="1h",
        status="OPEN",
    )

    records = strategy_api._latest_candidates(
        [latest_snapshot],
        [],
        [long_trade],
        [],
        24,
    )

    assert records[0]["paper_trade_id"] is None
    assert records[0]["lifecycle"] == "ELIGIBLE_NOT_SELECTED"
