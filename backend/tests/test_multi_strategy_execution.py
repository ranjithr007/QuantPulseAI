from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.paper_trade_api import _paper_trade_candidate_rank
from app.api.v1.signals_api import _persist_ready_watchlist_payload
from app.api.v1.signals_api import _persist_strategy_candidates
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.trade_plan import TradePlan
from app.database.sqlserver import Base
from app.repositories.trade_plan_repository import TradePlanRepository
from app.strategies.registry import CORE_FUSION_STRATEGY_ID
from app.strategies.registry import CORE_SIGNAL_STRATEGY_ID
from app.strategies.registry import MARKET_MOVE_STRATEGY_ID
from app.strategies.registry import STRATEGY_REGISTRY


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _core_payload(now, *, ready=True):
    component_scores = {
        "feature": {
            "score": 20.0 if ready else 5.0,
            "value": "BULLISH" if ready else "NEUTRAL",
            "reason": "Feature trend bullish" if ready else "Feature neutral",
        },
        "regime": {
            "score": 20.0 if ready else 5.0,
            "value": "BULL_PULLBACK" if ready else "RANGE",
            "reason": "Bull regime" if ready else "Neutral regime",
        },
        "orderflow": {
            "score": 22.0 if ready else 5.0,
            "value": "BUYERS_CONTROL" if ready else "BALANCED",
            "reason": "Buyers control flow" if ready else "Balanced flow",
        },
        "smc": {
            "score": 22.0 if ready else 5.0,
            "value": "LONG" if ready else "NEUTRAL",
            "reason": "SMC bullish" if ready else "SMC neutral",
        },
    }
    return {
        "symbol": "BNBUSDT",
        "mode": "intraday",
        "timeframes_used": ["1h", "2h", "4h", "1d"],
        "timeframes": [
            {
                "timeframe": timeframe,
                "candle_time": now,
                "status": "OK",
                "score": 55.0 if ready else 22.0,
                "confidence": 55.0 if ready else 22.0,
                "bias": "BULLISH" if ready else "NEUTRAL",
                "current_price": 700.0,
                "atr": 7.0,
                "freshness": {"is_stale": False},
                "inputs": {
                    name: {"is_stale": False}
                    for name in ("feature", "regime", "orderflow", "smc")
                },
                "component_scores": {
                    **component_scores,
                    "regime": {
                        **component_scores["regime"],
                        "value": (
                            "BULL_PULLBACK"
                            if timeframe in {"1h", "2h"}
                            else "RANGE_ACCUMULATION"
                        ) if ready else "RANGE",
                    },
                },
            }
            for timeframe in ("1h", "2h", "4h", "1d")
        ],
        "confirmation": {"confidence": 55.0 if ready else 22.0},
        "trigger": {
            "status": "READY" if ready else "WAIT",
            "side": "LONG" if ready else None,
            "entry_timeframe": "1h",
            "reason": "Core signal passed" if ready else "Core signal is WAIT",
            "conditions": [],
        },
        "trade_plan": (
            {
                "entry": 700.0,
                "stop_loss": 694.75,
                "target1": 710.5,
                "target2": 716.1,
                "risk_reward": 2.1,
            }
            if ready
            else None
        ),
        "trade_plan_validation": {
            "is_valid": ready,
            "errors": [] if ready else ["Signal is WAIT"],
        },
    }


def _market_move(now, *, carry_ready=False):
    payload = {
        "status": "READY",
        "quality_state": "OK",
        "direction": "BULLISH",
        "score": 64.0,
        "confidence": 64.0,
        "effective_timestamp": now,
        "data_generation_id": "bnb-market-move-1",
        "spot": {
            "timeframes": [
                {
                    "timeframe": timeframe,
                    "status": "READY",
                    "direction": "BULLISH",
                    "score": score,
                    "spot_price": 702.0,
                    "ema20": 700.0,
                    "spot_cvd_percent": 2.0,
                    "support": {
                        "lower": 694.0,
                        "upper": 700.0,
                        "center": 697.0,
                        "tests": 3,
                        "distance_percent": -0.71,
                        "latest_rejected": True,
                        "breakdown_accepted": False,
                    },
                    "resistance": {
                        "lower": 710.0,
                        "upper": 714.0,
                        "center": 712.0,
                        "tests": 3,
                        "distance_percent": 1.42,
                        "latest_rejected": False,
                        "breakout_accepted": False,
                    },
                    "source_timestamp": now,
                }
                for timeframe, score in (
                    ("1h", 52.0),
                    ("2h", 58.0),
                    ("4h", 61.0),
                    ("1d", 64.0),
                )
            ]
        },
    }
    if carry_ready:
        payload.update(
            {
                "components": {"derivatives": 8.0, "liquidation": 8.0},
                "derivatives": {
                    "funding_rate": 0.0001,
                    "open_interest_change_percent": 2.0,
                },
                "liquidation": {
                    "status": "READY",
                    "data_quality": "OBSERVED",
                    "bias": "HUNT_SHORTS",
                },
            }
        )
    return payload


def _evaluate_and_persist(db, core_payload, market_move):
    repo = TradePlanRepository()
    records = []
    for candidate in _persist_strategy_candidates(db, core_payload, market_move):
        definition = candidate["definition"]
        participation = (
            market_move
            if definition["requires_market_participation_confirmation"]
            else object()
        )
        kwargs = {}
        if definition["requires_market_participation_confirmation"]:
            kwargs["market_participation"] = participation
        records.append(
            _persist_ready_watchlist_payload(
                db,
                repo,
                candidate["payload"],
                strategy_snapshot=candidate["snapshot"],
                strategy=definition,
                **kwargs,
            )
        )
    return records


def test_individual_and_combined_strategies_create_separate_candidate_plans():
    db = _session()
    now = datetime.now(timezone.utc)
    try:
        records = _evaluate_and_persist(
            db,
            _core_payload(now, ready=True),
            _market_move(now, carry_ready=True),
        )

        assert {item["strategy_id"] for item in records} == set(STRATEGY_REGISTRY)
        assert all(item["action"] == "saved" for item in records)
        plans = db.query(TradePlan).filter(TradePlan.status == "OPEN").all()
        assert len(plans) == len(STRATEGY_REGISTRY)
        assert {item.strategy_id for item in plans} == set(STRATEGY_REGISTRY)
        assert len({item.strategy_decision_snapshot_id for item in plans}) == len(
            STRATEGY_REGISTRY
        )
        assert db.query(DecisionSnapshot).count() == len(STRATEGY_REGISTRY)
    finally:
        db.close()


def test_market_move_can_produce_a_plan_when_core_signal_is_wait():
    db = _session()
    now = datetime.now(timezone.utc)
    try:
        records = _evaluate_and_persist(
            db,
            _core_payload(now, ready=False),
            _market_move(now),
        )
        by_strategy = {item["strategy_id"]: item for item in records}

        assert by_strategy[CORE_SIGNAL_STRATEGY_ID]["action"] == "skipped_not_ready"
        assert by_strategy[CORE_FUSION_STRATEGY_ID]["action"] == "skipped_not_ready"
        assert by_strategy[MARKET_MOVE_STRATEGY_ID]["action"] == "saved"
        plan = db.query(TradePlan).filter(TradePlan.status == "OPEN").one()
        assert plan.strategy_id == MARKET_MOVE_STRATEGY_ID
        assert plan.side == "LONG"
        assert plan.entry_price == 702.0
    finally:
        db.close()


def test_strategy_scan_accepts_serialized_market_move_timestamps():
    db = _session()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    market_move = _market_move(now, carry_ready=True)
    market_move["effective_timestamp"] = now.isoformat().replace("+00:00", "Z")
    for timeframe in market_move["spot"]["timeframes"]:
        timeframe["source_timestamp"] = now.isoformat().replace("+00:00", "Z")

    try:
        records = _evaluate_and_persist(
            db,
            _core_payload(now, ready=True),
            market_move,
        )

        assert {item["strategy_id"] for item in records} == set(STRATEGY_REGISTRY)
        assert db.query(DecisionSnapshot).count() == len(STRATEGY_REGISTRY)
        market_move_snapshot = (
            db.query(DecisionSnapshot)
            .filter(DecisionSnapshot.strategy_id == MARKET_MOVE_STRATEGY_ID)
            .one()
        )
        assert market_move_snapshot.source_timestamp == now.replace(tzinfo=None)
    finally:
        db.close()


def test_same_candle_rescan_persists_current_decision_and_queue_state():
    db = _session()
    candle_time = datetime.now(timezone.utc)
    try:
        ready_records = _evaluate_and_persist(
            db,
            _core_payload(candle_time, ready=True),
            _market_move(candle_time, carry_ready=True),
        )
        assert all(item["action"] == "saved" for item in ready_records)
        assert db.query(TradePlan).filter(TradePlan.status == "OPEN").count() == len(
            STRATEGY_REGISTRY
        )

        repeated_ready_records = _evaluate_and_persist(
            db,
            _core_payload(candle_time, ready=True),
            _market_move(candle_time, carry_ready=True),
        )
        assert all(
            item["action"] == "skipped_existing_open"
            for item in repeated_ready_records
        )
        assert db.query(TradePlan).filter(TradePlan.status == "OPEN").count() == len(
            STRATEGY_REGISTRY
        )
        assert db.query(DecisionSnapshot).count() == len(STRATEGY_REGISTRY) * 2
        latest_snapshot_ids = {}
        for row in (
            db.query(DecisionSnapshot)
            .order_by(
                DecisionSnapshot.effective_timestamp.desc(),
                DecisionSnapshot.id.desc(),
            )
            .all()
        ):
            latest_snapshot_ids.setdefault(row.strategy_id, row.id)
        for plan in db.query(TradePlan).filter(TradePlan.status == "OPEN").all():
            assert (
                plan.strategy_decision_snapshot_id
                == latest_snapshot_ids[plan.strategy_id]
            )

        blocked_records = _evaluate_and_persist(
            db,
            _core_payload(candle_time, ready=False),
            {
                **_market_move(candle_time),
                "status": "WAIT",
                "direction": "NEUTRAL",
                "score": 0.0,
                "confidence": 0.0,
            },
        )

        assert all(item["action"] != "saved" for item in blocked_records)
        assert db.query(TradePlan).filter(TradePlan.status == "OPEN").count() == 0
        assert db.query(DecisionSnapshot).count() == len(STRATEGY_REGISTRY) * 3

        latest = (
            db.query(DecisionSnapshot)
            .filter(DecisionSnapshot.strategy_id == CORE_SIGNAL_STRATEGY_ID)
            .order_by(
                DecisionSnapshot.effective_timestamp.desc(),
                DecisionSnapshot.id.desc(),
            )
            .first()
        )
        assert latest.source_timestamp == candle_time.replace(tzinfo=None)
        assert latest.decision == "BLOCKED"
        assert latest.effective_timestamp > latest.source_timestamp
    finally:
        db.close()


def test_combined_strategy_wins_a_true_rank_tie_without_multiple_coin_entries():
    common = {
        "risk_decision": {"confidence": 64.0},
        "trade_plan": {
            "confidence": 64.0,
            "risk_reward": 2.1,
            "entry_timeframe": "1h",
            "created_at": datetime.now(timezone.utc),
            "id": 1,
        },
    }
    individual = {
        **common,
        "trade_plan": {
            **common["trade_plan"],
            "strategy_id": MARKET_MOVE_STRATEGY_ID,
        },
    }
    combined = {
        **common,
        "trade_plan": {
            **common["trade_plan"],
            "strategy_id": CORE_FUSION_STRATEGY_ID,
        },
    }

    assert _paper_trade_candidate_rank(combined) > _paper_trade_candidate_rank(individual)
