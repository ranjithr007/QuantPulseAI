import json

from app.api.v1.paper_trade_api import _official_regime_quarantine_blockers
from app.api.v1.paper_trade_api import _annotate_candidate_arbitration
from app.paper_trading.strategy_evidence import build_official_strategy_evidence
from app.paper_trading.strategy_evidence import strategy_evidence_blockers
from app.paper_trading.strategy_evidence import strategy_evidence_for_plan
from datetime import datetime, timedelta


def test_bull_pullback_is_quarantined_only_at_official_execution_gate():
    blockers = _official_regime_quarantine_blockers(
        {"trade_plan": {"regime": "BULL_PULLBACK"}}
    )

    assert len(blockers) == 1
    assert "quarantined" in blockers[0]
    assert "research candidate evidence remains enabled" in blockers[0]


def test_other_regimes_remain_available_to_existing_risk_gates():
    assert not _official_regime_quarantine_blockers(
        {"trade_plan": {"regime": "BEAR_RALLY"}}
    )


def _closed_trade(pnl, *, strategy_id="REGIME_TREND", version="regime_trend_v1"):
    return {
        "symbol": "BTCUSDT",
        "status": "CLOSED",
        "entry_timeframe": "1h",
        "strategy_id": strategy_id,
        "strategy_version": version,
        "pnl_percent": pnl,
    }


def test_mature_negative_strategy_revision_fails_evidence_gate():
    evidence_by_key = build_official_strategy_evidence(
        [_closed_trade(1.0)] * 5 + [_closed_trade(-1.0)] * 25
    )
    evidence = strategy_evidence_for_plan(
        evidence_by_key,
        {
            "strategy_id": "REGIME_TREND",
            "strategy_version": "regime_trend_v1",
        },
    )
    blockers = strategy_evidence_blockers(evidence)

    assert len(blockers) == 1
    assert evidence["status"] == "FAILED_EXPECTANCY"
    assert evidence["closed_trades"] == 30
    assert evidence["expectancy_percent"] < 0
    assert "failed the production expectancy gate" in blockers[0]


def test_immature_strategy_revision_remains_research_only():
    evidence_by_key = build_official_strategy_evidence(
        [_closed_trade(1.0, strategy_id="TREND_PULLBACK", version="v2")] * 29
    )
    evidence = strategy_evidence_for_plan(
        evidence_by_key,
        {"strategy_id": "TREND_PULLBACK", "strategy_version": "v2"},
    )

    assert evidence["status"] == "INSUFFICIENT_EVIDENCE"
    assert evidence["closed_trades"] == 29
    assert "29/30" in strategy_evidence_blockers(evidence)[0]


def test_profitable_mature_strategy_revision_is_promotable():
    evidence_by_key = build_official_strategy_evidence(
        [
            *[
                _closed_trade(1.5, strategy_id="TREND_PULLBACK", version="v2")
                for _ in range(20)
            ],
            *[
                _closed_trade(-0.5, strategy_id="TREND_PULLBACK", version="v2")
                for _ in range(10)
            ],
        ]
    )
    evidence = strategy_evidence_for_plan(
        evidence_by_key,
        {"strategy_id": "TREND_PULLBACK", "strategy_version": "v2"},
    )

    assert evidence["status"] == "PROMOTABLE"
    assert evidence["official_execution_allowed"] is True
    assert evidence["profit_factor"] == 6.0
    assert strategy_evidence_blockers(evidence) == []


def test_new_revision_does_not_inherit_old_revision_evidence():
    evidence_by_key = build_official_strategy_evidence(
        [_closed_trade(1.0)] * 30
    )
    new_revision = strategy_evidence_for_plan(
        evidence_by_key,
        {
            "strategy_id": "REGIME_TREND",
            "strategy_version": "regime_trend_v2",
        },
    )

    assert new_revision["closed_trades"] == 0
    assert new_revision["status"] == "INSUFFICIENT_EVIDENCE"


def test_deadline_breached_time_exit_is_excluded_from_promotion_evidence():
    closed_at = datetime(2026, 9, 14, 12, 0)
    contaminated = {
        **_closed_trade(99.0, strategy_id="TREND_PULLBACK", version="v2"),
        "exit_reason": "TIME_EXIT",
        "max_hold_hours": 48,
        "opened_at": closed_at - timedelta(hours=60),
        "closed_at": closed_at,
    }
    evidence = strategy_evidence_for_plan(
        build_official_strategy_evidence(
            [
                *[_closed_trade(1.0, strategy_id="TREND_PULLBACK", version="v2") for _ in range(29)],
                contaminated,
            ]
        ),
        {"strategy_id": "TREND_PULLBACK", "strategy_version": "v2"},
    )

    assert evidence["closed_trades"] == 29
    assert evidence["total_observed_closed_trades"] == 30
    assert evidence["excluded_operationally_contaminated_trades"] == 1
    assert evidence["status"] == "INSUFFICIENT_EVIDENCE"
    assert "29/30 clean measured" in strategy_evidence_blockers(evidence)[0]


def test_stale_recorded_stop_trigger_is_excluded_from_promotion_evidence():
    stale = {
        **_closed_trade(99.0, strategy_id="TREND_PULLBACK", version="v2"),
        "exit_reason": "STOP",
        "exit_evidence_json": json.dumps(
            {
                "classification": "INITIAL_STOP",
                "evidence_kind": "CANDLE_OHLC",
                "observed_at": "2026-09-14T12:00:00Z",
                "quote_age_seconds": 6.0,
            }
        ),
    }
    evidence = strategy_evidence_for_plan(
        build_official_strategy_evidence(
            [
                *[_closed_trade(1.0, strategy_id="TREND_PULLBACK", version="v2") for _ in range(29)],
                stale,
            ]
        ),
        {"strategy_id": "TREND_PULLBACK", "strategy_version": "v2"},
    )

    assert evidence["closed_trades"] == 29
    assert evidence["excluded_operationally_contaminated_trades"] == 1
    assert evidence["status"] == "INSUFFICIENT_EVIDENCE"


def test_strategy_paper_evidence_can_promote_without_double_counting_official_plan():
    official = [
        {
            **_closed_trade(1.0, strategy_id="MARKET_MOVE", version="v3"),
            "trade_plan_id": 1,
        }
    ]
    research = [
        {
            **_closed_trade(-99.0, strategy_id="MARKET_MOVE", version="v3"),
            "trade_plan_id": 1,
        },
        *[
            {
                **_closed_trade(1.0, strategy_id="MARKET_MOVE", version="v3"),
                "trade_plan_id": plan_id,
            }
            for plan_id in range(2, 31)
        ],
    ]

    evidence = strategy_evidence_for_plan(
        build_official_strategy_evidence(official, research),
        {"strategy_id": "MARKET_MOVE", "strategy_version": "v3"},
    )

    assert evidence["closed_trades"] == 30
    assert evidence["official_paper_closed_trades"] == 1
    assert evidence["strategy_paper_closed_trades"] == 29
    assert evidence["evidence_source"] == "OFFICIAL_AND_STRATEGY_PAPER"
    assert evidence["status"] == "PROMOTABLE"


def test_candidate_api_exposes_strategy_evidence_and_executor_blocker():
    candidate = {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "eligible": True,
        "blocked_reasons": [],
        "risk_decision": {"confidence": 65},
        "paper_sizing": {"leverage": 2, "position_notional_inr": 100_000},
        "trade_plan": {
            "id": 1,
            "strategy_id": "REGIME_TREND",
            "strategy_version": "regime_trend_v1",
            "regime": "RANGE_ACCUMULATION",
            "confidence": 65,
            "risk_reward": 2.1,
            "entry_timeframe": "1h",
        },
    }
    automation = {
        "enabled": True,
        "locked": False,
        "emergencyStop": False,
        "allowedSymbols": ["BTCUSDT"],
        "minConfidence": 40,
        "direction": "BOTH",
        "executionMode": "PAPER",
        "liveExecutionEnabled": False,
        "maxLeverage": 5,
        "maxPositionSize": 200_000,
    }

    evidence = build_official_strategy_evidence(
        [_closed_trade(1.0)] * 5 + [_closed_trade(-1.0)] * 25
    )
    record = _annotate_candidate_arbitration(
        [candidate],
        automation,
        strategy_evidence_by_key=evidence,
    )[0]

    assert record["arbitration"]["status"] == "BLOCKED"
    assert record["arbitration"]["selected_for_official_execution"] is False
    assert record["strategy_evidence"]["status"] == "FAILED_EXPECTANCY"
    assert "REGIME_TREND@regime_trend_v1 failed" in (
        record["arbitration"]["executor_blockers"][0]
    )


def test_candidate_api_keeps_each_strategy_revision_evidence_isolated():
    first = {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "eligible": True,
        "blocked_reasons": [],
        "risk_decision": {"confidence": 65},
        "paper_sizing": {},
        "trade_plan": {
            "id": 1,
            "strategy_id": "REGIME_TREND",
            "strategy_version": "v1",
            "entry_timeframe": "1h",
        },
    }
    second = {
        **first,
        "trade_plan": {
            **first["trade_plan"],
            "id": 2,
            "strategy_id": "TREND_PULLBACK",
            "strategy_version": "v2",
        },
    }
    evidence = build_official_strategy_evidence(
        [
            *[_closed_trade(-1.0, version="v1") for _ in range(30)],
            *[
                _closed_trade(
                    1.0,
                    strategy_id="TREND_PULLBACK",
                    version="v2",
                )
                for _ in range(5)
            ],
        ]
    )

    records = _annotate_candidate_arbitration(
        [first, second],
        {
            "enabled": True,
            "locked": False,
            "emergencyStop": False,
            "allowedSymbols": ["BTCUSDT"],
            "minConfidence": 40,
            "direction": "BOTH",
            "executionMode": "PAPER",
            "liveExecutionEnabled": False,
            "maxLeverage": 5,
            "maxPositionSize": 200_000,
        },
        strategy_evidence_by_key=evidence,
    )

    assert records[0]["strategy_evidence"]["strategy_revision"] == "REGIME_TREND@v1"
    assert records[0]["strategy_evidence"]["status"] == "FAILED_EXPECTANCY"
    assert records[1]["strategy_evidence"]["strategy_revision"] == "TREND_PULLBACK@v2"
    assert records[1]["strategy_evidence"]["status"] == "INSUFFICIENT_EVIDENCE"
