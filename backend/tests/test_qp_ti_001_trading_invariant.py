from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.v1 import paper_trade_api
from app.api.v1 import risk_api
from app.api.v1.signals_api import _market_direction
from app.api.v1.signals_api import _watchlist_computed_risk_payload
from app.api.v1.signals_api import _watchlist_eligibility
from app.api.v1.signals_api import _watchlist_risk_payload
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
from app.trading.trade_plan_engine import build_trade_plan


def _candidate(plan_id, timeframe, confidence, *, side="LONG", risk_reward=2.0):
    direction = 1 if side == "LONG" else -1
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
            "entry_price": 100.0,
            "stop_loss": 100.0 - direction * 0.75,
            "target1": 100.0 + direction * 1.5,
            "target2": 100.0 + direction * 2.3,
            "exit_policy": "PAPER_STAGED_EXIT_V2",
            "created_at": datetime(2026, 8, 11, plan_id, tzinfo=timezone.utc),
        },
        "risk_decision": {
            "id": plan_id,
            "confidence": confidence,
            "risk_percent": 1.0,
            "position_size": 1.0,
            "risk_reward": risk_reward,
        },
        "fill_profile": {"fee_bps": 7.5},
        "paper_sizing": {
            "leverage": 5.0,
            "position_notional_inr": 170_000.0,
            "margin_used_inr": 34_000.0,
        },
    }


@pytest.fixture(autouse=True)
def _fresh_paper_entry_mark(monkeypatch):
    monkeypatch.setattr(
        paper_trade_api,
        "_current_paper_entry_mark",
        lambda symbol: {
            "symbol": symbol,
            "mark_price": 120.0,
            "observed_at": datetime.now(timezone.utc),
            "source": "TEST_MARK",
        },
    )


def _enabled_automation_settings():
    return {
        "enabled": True,
        "locked": False,
        "emergencyStop": False,
        "allowedSymbols": ["BTCUSDT", "ETHUSDT"],
        "maxRiskPerTrade": 1.0,
        "maxRiskPerTradeEnabled": False,
        "dailyLossLimit": 4.0,
        "dailyLossLimitEnabled": False,
        "maxOpenTrades": 4,
        "maxOpenTradesEnabled": False,
        "maxLeverage": 5,
        "maxPositionSize": 170_000.0,
        "minConfidence": 40.0,
        "direction": "BOTH",
        "executionMode": "PAPER",
        "liveExecutionEnabled": False,
    }


@pytest.mark.parametrize(
    ("setting_overrides", "expected_reason"),
    [
        ({"enabled": False}, "Paper-trade automation is disabled"),
        ({"locked": True}, "Paper-trade automation is locked"),
        ({"emergencyStop": True}, "Automation emergency stop is active"),
        ({"allowedSymbols": ["ETHUSDT"]}, "BTCUSDT is not in the automation allowlist"),
        ({"direction": "SHORT"}, "LONG entries are disabled"),
        (
            {"maxRiskPerTrade": 0.5, "maxRiskPerTradeEnabled": True},
            "risk percentage exceeds",
        ),
        ({"maxLeverage": 3}, "leverage exceeds"),
        ({"maxPositionSize": 70_000}, "position size exceeds"),
        ({"minConfidence": 80}, "confidence is below"),
        ({"executionMode": "LIVE"}, "execution mode is not PAPER"),
        ({"liveExecutionEnabled": True}, "Live execution must remain disabled"),
    ],
)
def test_final_paper_execution_boundary_enforces_automation_controls(
    setting_overrides,
    expected_reason,
):
    settings = {**_enabled_automation_settings(), **setting_overrides}

    reasons = paper_trade_api._automation_execution_blockers(
        settings,
        _candidate(1, "1h", 72),
    )

    assert any(expected_reason in reason for reason in reasons)


def test_executor_fails_closed_when_automation_settings_are_unavailable(monkeypatch):
    candidate = _candidate(1, "1h", 72)

    class DummyDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeRepo:
        def save_candidate(self, db, item):
            raise AssertionError("A locked executor must not persist a paper trade")

    monkeypatch.setattr(paper_trade_api, "SessionLocal", DummyDb)
    monkeypatch.setattr(
        paper_trade_api,
        "build_paper_trade_candidates",
        lambda *args, **kwargs: (None, [candidate]),
    )
    monkeypatch.setattr(paper_trade_api, "PaperTradeRepository", FakeRepo)
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_wallet_snapshot",
        lambda db, trades: {
            "open_position_count": 0,
            "remaining_margin_capacity_inr": 85_000,
        },
    )
    monkeypatch.setattr(
        paper_trade_api,
        "get_automation_settings",
        lambda db: (_ for _ in ()).throw(RuntimeError("settings unavailable")),
    )

    result = paper_trade_api.execute_paper_trade_candidates_for_symbol()

    assert result["executed_count"] == 0
    assert result["skipped"][0]["action"] == "skipped_automation_control"
    assert "Paper-trade automation is disabled" in result["skipped"][0]["blocked_reasons"]
    assert "Paper-trade automation is locked" in result["skipped"][0]["blocked_reasons"]


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
    governed_limits = risk_api._normalize_auto_settings(
        {"dailyLossLimit": 15, "maxOpenTrades": 20}
    )
    assert governed_limits["dailyLossLimit"] == 4
    assert governed_limits["maxOpenTrades"] == 4


def test_selected_timeframe_confidence_drives_watchlist_and_risk():
    governed = build_trade_plan("SHORT", 100, 1, confidence=49)
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
            "entry": governed["entry"],
            "stop_loss": governed["stop_loss"],
            "target1": governed["target1"],
            "target2": governed["target2"],
            "risk_reward": governed["risk_reward"],
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
    assert row["target1"] == governed["target1"]
    assert row["target2"] == governed["target2"]

    aligned = _watchlist_row(
        payload,
        market_participation={
            "status": "READY",
            "quality_state": "OK",
            "direction": "BEARISH",
            "score": -53,
            "confidence": 53,
            "effective_timestamp": datetime.now(timezone.utc),
        },
    )
    assert aligned["eligibility_allowed"] is True
    assert aligned["combined_execution"] == {
        "allowed": True,
        "status": "ELIGIBLE",
        "reason": aligned["eligibility_reason"],
        "selected_timeframe": "4h",
        "side": "SHORT",
        "score": -49,
        "confidence": 49,
        "market_participation_status": "ALIGNED",
    }
    assert aligned["market_participation"]["score"] == -53

    conflicting = _watchlist_row(
        payload,
        market_participation={
            "status": "READY",
            "quality_state": "OK",
            "direction": "BULLISH",
            "score": 53,
            "confidence": 53,
            "effective_timestamp": datetime.now(timezone.utc),
        },
    )
    assert conflicting["eligibility_allowed"] is False
    assert conflicting["eligibility_label"] == "Blocked by participation"
    assert conflicting["eligibility_status"] == "BLOCKED_PARTICIPATION"
    assert "SHORT requires BEARISH" in conflicting["eligibility_reason"]


def test_persisted_rejected_risk_cannot_be_reported_as_eligible():
    persisted = _watchlist_risk_payload(
        SimpleNamespace(
            symbol="SOLUSDT",
            signal="LONG",
            entry_price=100,
            target1=101.5,
            created_at=datetime.now(timezone.utc),
            decision="REJECT",
            reason="Risk engine rejected signal",
        ),
        stale_after_seconds=900,
    )

    eligibility = _watchlist_eligibility(
        {
            "trigger": {
                "status": "READY",
                "side": "LONG",
                "reason": "4h LONG entry trigger is ready",
                "conditions": [],
            },
            "trade_plan": {
                "entry": 100,
                "stop_loss": 99.25,
                "target1": 101.5,
                "risk_reward": 2.0,
            },
            "trade_plan_validation": {"is_valid": True, "errors": []},
        },
        risk=persisted,
    )

    assert persisted["decision"] == "REJECT"
    assert persisted["is_usable"] is False
    assert persisted["status"] == "current_rejected"
    assert "Risk engine rejected signal" in persisted["validation_errors"]
    assert eligibility == {
        "label": "Blocked by risk",
        "tone": "rose",
        "reason": "Risk engine rejected signal",
        "allowed": False,
        "status": "BLOCKED_RISK",
    }


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
    lock_calls = []

    class DummyDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeRepo:
        def acquire_account_execution_lock(self, db):
            lock_calls.append("lock")

        def all_trades(self, db):
            return []

        def has_open_trade(self, db, symbol, side=None):
            lock_calls.append("open-check")
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
        "_paper_wallet_snapshot",
        lambda db, trades, account_risk=None: {
            "open_position_count": 0,
            "remaining_margin_capacity_inr": 85_000,
        },
    )
    monkeypatch.setattr(paper_trade_api, "get_automation_settings", lambda db: object())
    monkeypatch.setattr(
        paper_trade_api,
        "automation_settings_payload",
        lambda row: _enabled_automation_settings(),
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_trade_payload",
        lambda trade, fill_profile=None: {"id": trade.id},
    )

    result = paper_trade_api.execute_paper_trade_candidates_for_symbol()

    assert [item["trade_plan"]["id"] for item in saved] == [3]
    assert lock_calls[:2] == ["lock", "open-check"]
    assert result["executed_count"] == 1
    assert sum(
        item["action"] == "skipped_weaker_symbol_candidate"
        for item in result["skipped"]
    ) == 2


def test_new_paper_entry_rebases_fill_stop_and_targets_from_fresh_mark():
    candidate = _candidate(9, "1h", 64)

    rebased, error = paper_trade_api._rebase_paper_trade_candidate(
        candidate,
        {
            "symbol": "BTCUSDT",
            "mark_price": 300.0,
            "observed_at": datetime.now(timezone.utc),
            "source": "TEST_MARK",
        },
    )

    assert error is None
    fill = rebased["fill_profile"]
    execution_risk = rebased["execution_risk"]
    entry = fill["entry_fill_price"]
    assert entry > 300.0
    assert fill["signal_planned_entry_price"] == 100.0
    assert fill["execution_mark_price"] == 300.0
    assert execution_risk["decision"] == "APPROVE"
    assert execution_risk["entry_price"] == entry
    assert execution_risk["stop_loss"] == round(entry * 0.9925, 2)
    assert execution_risk["target1"] == round(entry * 1.015, 2)
    assert execution_risk["target2"] == round(entry * 1.023, 2)
    assert candidate["trade_plan"]["entry_price"] == 100.0


def test_new_paper_entry_fails_closed_without_fresh_mark():
    candidate = _candidate(10, "1h", 64)

    rebased, error = paper_trade_api._rebase_paper_trade_candidate(candidate, None)

    assert rebased is candidate
    assert error == "Fresh execution mark price is unavailable"


def test_new_short_entry_recalculates_inverse_exit_bracket():
    candidate = _candidate(11, "4h", 49, side="SHORT")

    rebased, error = paper_trade_api._rebase_paper_trade_candidate(
        candidate,
        {
            "symbol": "BTCUSDT",
            "mark_price": 2.0,
            "observed_at": datetime.now(timezone.utc),
            "source": "TEST_MARK",
        },
    )

    assert error is None
    entry = rebased["fill_profile"]["entry_fill_price"]
    execution_risk = rebased["execution_risk"]
    assert entry < 2.0
    assert execution_risk["stop_loss"] == round(entry * 1.0075, 5)
    assert execution_risk["target1"] == round(entry * 0.985, 5)
    assert execution_risk["target2"] == round(entry * 0.977, 5)


def test_active_btc_trade_does_not_block_eligible_eth_candidate(monkeypatch):
    btc = _candidate(1, "1h", 80)
    eth = {
        **_candidate(2, "4h", 80),
        "symbol": "ETHUSDT",
    }
    saved = []

    class DummyDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeRepo:
        def acquire_account_execution_lock(self, db):
            pass

        def all_trades(self, db):
            return []

        def has_open_trade(self, db, symbol, side=None):
            return symbol == "BTCUSDT"

        def has_trade_for_plan(self, db, trade_plan_id):
            return False

        def save_candidate(self, db, candidate):
            saved.append(candidate)
            return SimpleNamespace(id=100)

    monkeypatch.setattr(paper_trade_api, "SessionLocal", DummyDb)
    monkeypatch.setattr(
        paper_trade_api,
        "build_paper_trade_candidates",
        lambda *args, **kwargs: (None, [btc, eth]),
    )
    monkeypatch.setattr(paper_trade_api, "PaperTradeRepository", FakeRepo)
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_wallet_snapshot",
        lambda db, trades, account_risk=None: {
            "open_position_count": 0,
            "remaining_margin_capacity_inr": 85_000,
        },
    )
    monkeypatch.setattr(paper_trade_api, "get_automation_settings", lambda db: object())
    monkeypatch.setattr(
        paper_trade_api,
        "automation_settings_payload",
        lambda row: _enabled_automation_settings(),
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_trade_payload",
        lambda trade, fill_profile=None: {"id": trade.id},
    )

    result = paper_trade_api.execute_paper_trade_candidates_for_symbol()

    assert [item["symbol"] for item in saved] == ["ETHUSDT"]
    assert result["executed_count"] == 1
    assert any(
        item["symbol"] == "BTCUSDT"
        and item["action"] == "skipped_existing_open_paper_trade"
        for item in result["skipped"]
    )


def test_executor_blocks_only_same_side_during_post_stop_cooldown(monkeypatch):
    candidate = _candidate(12, "1h", 64, side="LONG")
    stopped_trade = SimpleNamespace(
        id=91,
        symbol="BTCUSDT",
        side="LONG",
        status="CLOSED",
        exit_reason="STOP",
        closed_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )

    class DummyDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeRepo:
        def acquire_account_execution_lock(self, db):
            pass

        def all_trades(self, db):
            return [stopped_trade]

        def has_open_trade(self, db, symbol, side=None):
            return False

        def save_candidate(self, db, item):
            raise AssertionError("Same-side cooldown must prevent persistence")

    monkeypatch.setattr(paper_trade_api, "SessionLocal", DummyDb)
    monkeypatch.setattr(
        paper_trade_api,
        "build_paper_trade_candidates",
        lambda *args, **kwargs: (None, [candidate]),
    )
    monkeypatch.setattr(paper_trade_api, "PaperTradeRepository", FakeRepo)
    monkeypatch.setattr(paper_trade_api, "get_automation_settings", lambda db: object())
    monkeypatch.setattr(
        paper_trade_api,
        "automation_settings_payload",
        lambda row: _enabled_automation_settings(),
    )

    result = paper_trade_api.execute_paper_trade_candidates_for_symbol()

    assert result["executed_count"] == 0
    assert result["skipped"][0]["action"] == "skipped_same_side_stop_cooldown"
    assert result["skipped"][0]["stop_reentry_cooldown"]["blocked_side"] == "LONG"


def test_candidate_exposes_post_stop_cooldown_as_coin_level_blocker():
    trade = SimpleNamespace(
        id=12,
        symbol="BTCUSDT",
        side="LONG",
        status="OPEN",
        entry_price=100.0,
        stop_loss=99.25,
        target1=101.5,
        target2=102.3,
        target3=None,
        risk_reward=2.0,
        confidence=64.0,
        created_at=datetime.now(timezone.utc),
    )
    cooldown = {
        "active": True,
        "symbol": "BTCUSDT",
        "blocked_side": "LONG",
        "cooldown_minutes": 30,
        "remaining_seconds": 1200,
    }

    candidate = paper_trade_api._paper_trade_candidate(
        trade,
        None,
        900,
        account_risk={"risk_available": True, "limit_reached": False},
        paper_wallet={
            "open_position_count": 0,
            "remaining_margin_capacity_inr": 85_000,
        },
        stop_reentry_cooldown=cooldown,
    )

    assert candidate["eligible"] is False
    assert candidate["stop_reentry_cooldown"] == cooldown
    assert (
        paper_trade_api.PAPER_STOP_REENTRY_COOLDOWN_REASON
        in candidate["blocker_scopes"]["coin"]
    )


def test_candidate_blocks_stale_current_orderflow_at_trade_scope():
    trade = SimpleNamespace(
        id=14,
        symbol="ETHUSDT",
        side="LONG",
        status="OPEN",
        entry_price=100.0,
        stop_loss=99.25,
        target1=101.5,
        target2=102.3,
        target3=None,
        risk_reward=2.0,
        confidence=53.4,
        created_at=datetime.now(timezone.utc),
    )

    candidate = paper_trade_api._paper_trade_candidate(
        trade,
        None,
        900,
        current_signal_validation={
            "status": "INVALIDATED",
            "trade_allowed": False,
            "signal": "LONG",
            "reasons": ["Orderflow input is stale"],
        },
        account_risk={"risk_available": True, "limit_reached": False},
        paper_wallet={
            "open_position_count": 0,
            "remaining_margin_capacity_inr": 85_000,
        },
    )

    assert candidate["eligible"] is False
    assert "Orderflow input is stale" in candidate["blocker_scopes"]["trade"]


def test_executor_allows_opposite_side_during_post_stop_cooldown(monkeypatch):
    candidate = _candidate(13, "1h", 64, side="SHORT")
    stopped_trade = SimpleNamespace(
        id=92,
        symbol="BTCUSDT",
        side="LONG",
        status="CLOSED",
        exit_reason="STOP",
        closed_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    saved = []

    class DummyDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeRepo:
        def acquire_account_execution_lock(self, db):
            pass

        def all_trades(self, db):
            return [stopped_trade]

        def has_open_trade(self, db, symbol, side=None):
            return False

        def has_trade_for_plan(self, db, trade_plan_id):
            return False

        def save_candidate(self, db, item):
            saved.append(item)
            return SimpleNamespace(id=93)

    monkeypatch.setattr(paper_trade_api, "SessionLocal", DummyDb)
    monkeypatch.setattr(
        paper_trade_api,
        "build_paper_trade_candidates",
        lambda *args, **kwargs: (None, [candidate]),
    )
    monkeypatch.setattr(paper_trade_api, "PaperTradeRepository", FakeRepo)
    monkeypatch.setattr(
        paper_trade_api,
        "_account_risk_snapshot",
        lambda db, trades: {
            "risk_available": True,
            "limit_reached": False,
            "current_prices": {},
        },
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_wallet_snapshot",
        lambda db, trades, account_risk=None: {
            "open_position_count": 0,
            "remaining_margin_capacity_inr": 85_000,
        },
    )
    monkeypatch.setattr(paper_trade_api, "get_automation_settings", lambda db: object())
    monkeypatch.setattr(
        paper_trade_api,
        "automation_settings_payload",
        lambda row: _enabled_automation_settings(),
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_trade_payload",
        lambda trade, fill_profile=None: {"id": trade.id},
    )

    result = paper_trade_api.execute_paper_trade_candidates_for_symbol()

    assert result["executed_count"] == 1
    assert saved[0]["side"] == "SHORT"


def test_executor_rechecks_account_capacity_under_lock_for_each_symbol(monkeypatch):
    btc = _candidate(1, "1h", 80)
    eth = {**_candidate(2, "4h", 80), "symbol": "ETHUSDT"}
    open_trades = []
    lock_count = 0

    class DummyDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeRepo:
        def acquire_account_execution_lock(self, db):
            nonlocal lock_count
            lock_count += 1

        def all_trades(self, db):
            return list(open_trades)

        def has_open_trade(self, db, symbol, side=None):
            return any(item.symbol == symbol for item in open_trades)

        def has_trade_for_plan(self, db, trade_plan_id):
            return False

        def save_candidate(self, db, candidate):
            trade = SimpleNamespace(
                id=len(open_trades) + 1,
                symbol=candidate["symbol"],
                status="OPEN",
            )
            open_trades.append(trade)
            return trade

    settings = {
        **_enabled_automation_settings(),
        "maxOpenTrades": 1,
        "maxOpenTradesEnabled": True,
    }
    monkeypatch.setattr(paper_trade_api, "SessionLocal", DummyDb)
    monkeypatch.setattr(
        paper_trade_api,
        "build_paper_trade_candidates",
        lambda *args, **kwargs: (None, [btc, eth]),
    )
    monkeypatch.setattr(paper_trade_api, "PaperTradeRepository", FakeRepo)
    monkeypatch.setattr(
        paper_trade_api,
        "_account_risk_snapshot",
        lambda db, trades: {
            "risk_available": True,
            "limit_reached": False,
            "current_prices": {},
        },
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_wallet_snapshot",
        lambda db, trades, account_risk=None: {
            "open_position_count": len(trades),
            "remaining_margin_capacity_inr": 85_000,
        },
    )
    monkeypatch.setattr(paper_trade_api, "get_automation_settings", lambda db: object())
    monkeypatch.setattr(
        paper_trade_api,
        "automation_settings_payload",
        lambda row: settings,
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_trade_payload",
        lambda trade, fill_profile=None: {"id": trade.id},
    )

    result = paper_trade_api.execute_paper_trade_candidates_for_symbol()

    assert lock_count == 2
    assert result["executed_count"] == 1
    assert result["executed"][0]["id"] == 1
    assert any(
        item["action"] == "skipped_account_open_trade_cap"
        for item in result["skipped"]
    )


def test_postgresql_account_execution_lock_is_transaction_scoped():
    statements = []

    class FakeDb:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params):
            statements.append((str(statement), params))

    assert PaperTradeRepository().acquire_account_execution_lock(FakeDb())
    assert "pg_advisory_xact_lock" in statements[0][0]
    assert statements[0][1]["lock_key"] == (
        PaperTradeRepository.ACCOUNT_EXECUTION_LOCK_KEY
    )


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
        "market_participation_trend",
        "watchlist_persist",
        "opportunity_coverage_recovery",
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
