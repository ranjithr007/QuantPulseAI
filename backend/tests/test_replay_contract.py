from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.backtesting.replay_contract import (
    build_point_in_time_stack,
    build_replay_input_contract,
    candles_as_of,
)
from app.backtesting.filtered_replay_engine import (
    _decision_timestamp,
    _timeframe_stack_gate,
)


def _candle(offset, *, final=True, close_offset=None):
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=offset)
    closed = opened + timedelta(hours=1 if close_offset is None else close_offset)
    return {
        "candle_time": opened,
        "open_time": opened,
        "close_time": closed,
        "is_final": final,
    }


def test_replay_contract_declares_official_stack_and_partial_multi_timeframe_scope():
    contract = build_replay_input_contract("1h")

    assert contract["official_timeframes"] == ["1h", "2h", "4h", "1d"]
    assert contract["higher_timeframes"] == ["2h", "4h", "1d"]
    assert contract["status"] == "PARTIAL_MULTI_TIMEFRAME"
    assert contract["as_of_policy"] == "FINAL_CLOSED_CANDLES_ONLY"


def test_replay_decision_clock_uses_candle_close_timestamp():
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closed = opened + timedelta(hours=1)

    assert _decision_timestamp(
        SimpleNamespace(candle_time=opened, close_time=closed)
    ) == closed


def test_candles_as_of_excludes_forming_and_future_closed_candles():
    candles = [_candle(0), _candle(1, final=False), _candle(2), _candle(3)]

    result = candles_as_of(candles, datetime(2026, 1, 1, 3, 30, tzinfo=timezone.utc))

    assert [item["candle_time"].hour for item in result] == [0, 2]


def test_point_in_time_stack_uses_one_cutoff_for_all_official_timeframes():
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles_by_timeframe = {}
    durations = {"1h": 1, "2h": 2, "4h": 4, "1d": 24}
    for timeframe, hours in durations.items():
        candles_by_timeframe[timeframe] = [
            {
                "candle_time": base + timedelta(hours=index * hours),
                "close_time": base + timedelta(hours=(index + 1) * hours),
                "is_final": True,
            }
            for index in range(70)
        ]

    observed = {}

    def feature_builder(symbol, timeframe, history, **timestamps):
        observed[timeframe] = {
            "count": len(history),
            "effective_timestamp": timestamps["effective_timestamp"],
            "latest_close": history[-1]["close_time"],
        }
        score = {"1h": 72, "2h": 68, "4h": 65, "1d": 61}[timeframe]
        return {"feature": {"final_score": score}}

    cutoff = base + timedelta(days=60)
    result = build_point_in_time_stack(
        "DOGEUSDT",
        candles_by_timeframe,
        cutoff,
        feature_builder=feature_builder,
    )

    assert result["status"] == "READY"
    assert result["timeframes_used"] == ["1h", "2h", "4h", "1d"]
    assert result["confirmation"]["trade_permission"] == "LONG_ALLOWED"
    assert all(item["effective_timestamp"] == cutoff for item in observed.values())
    assert all(item["latest_close"] <= cutoff for item in observed.values())


def test_point_in_time_stack_fails_closed_when_higher_history_is_missing():
    cutoff = datetime(2026, 1, 10, tzinfo=timezone.utc)

    result = build_point_in_time_stack(
        "DOGEUSDT",
        {"1h": [_candle(index) for index in range(60)]},
        cutoff,
        feature_builder=lambda *args, **kwargs: {"feature": {"final_score": 70}},
    )

    assert result["status"] == "INSUFFICIENT_HISTORY"
    assert result["confirmation"]["trade_permission"] == "BLOCKED"


def test_point_in_time_stack_prefers_governed_intelligence_signal_when_supplied():
    histories = {
        timeframe: [_candle(index) for index in range(60)]
        for timeframe in ("1h", "2h", "4h", "1d")
    }

    def intelligence_builder(symbol, timeframe, history, **timestamps):
        return {
            "feature": {"final_score": 80},
            "signal": {
                "signal": "LONG",
                "bias": "LONG",
                "confidence": 72,
                "score": 48,
            },
        }

    result = build_point_in_time_stack(
        "DOGEUSDT",
        histories,
        datetime(2026, 1, 10, tzinfo=timezone.utc),
        intelligence_builder=intelligence_builder,
    )

    assert result["component_scope"] == "CANDLE_DERIVED_FEATURE_REGIME_ORDERFLOW_SMC"
    assert result["confirmation"]["trade_permission"] == "LONG_ALLOWED"
    assert all(item["score"] == 48 for item in result["timeframes"])


def test_replay_gate_blocks_strong_higher_timeframe_conflict():
    context = {
        "status": "READY",
        "timeframes": [
            {"timeframe": "1h", "bias": "LONG"},
            {"timeframe": "2h", "bias": "NEUTRAL"},
            {"timeframe": "4h", "bias": "NEUTRAL"},
            {"timeframe": "1d", "bias": "WEAK_SHORT"},
        ],
        "confirmation": {
            "trade_permission": "WAIT",
            "stack_state": "MIXED_STRONG",
            "confidence_penalty": 15,
        },
    }

    penalty, blocks = _timeframe_stack_gate(context, "LONG")

    assert penalty == 0
    assert blocks == ["HIGHER_TIMEFRAME_CONFLICT"]


def test_replay_gate_penalizes_mixed_light_without_hard_block():
    context = {
        "status": "READY",
        "timeframes": [
            {"timeframe": "1h", "bias": "LONG"},
            {"timeframe": "2h", "bias": "NEUTRAL"},
            {"timeframe": "4h", "bias": "NEUTRAL"},
            {"timeframe": "1d", "bias": "NEUTRAL"},
        ],
        "confirmation": {
            "trade_permission": "WAIT",
            "stack_state": "MIXED_LIGHT",
            "confidence_penalty": 5,
        },
    }

    penalty, blocks = _timeframe_stack_gate(context, "LONG")

    assert penalty == 5
    assert blocks == []


def test_replay_gate_enforces_reconstructed_risk_and_executor_verdict():
    context = {
        "status": "READY",
        "timeframes": [
            {"timeframe": "1h", "bias": "LONG"},
            {"timeframe": "2h", "bias": "LONG"},
            {"timeframe": "4h", "bias": "LONG"},
            {"timeframe": "1d", "bias": "LONG"},
        ],
        "confirmation": {
            "trade_permission": "LONG_ALLOWED",
            "stack_state": "ALIGNED",
            "confidence_penalty": 0,
        },
        "decision_chain": {
            "signal": {"signal": "LONG"},
            "contradiction": {"trade_allowed": True},
            "risk": {"decision": "REJECT"},
            "executor": {"verdict": "BLOCKED"},
        },
    }

    penalty, blocks = _timeframe_stack_gate(context, "LONG")

    assert penalty == 0
    assert blocks == ["RISK_GATE_REJECTED"]


def test_research_replay_gate_can_measure_directional_coverage_without_chain():
    context = {
        "status": "READY",
        "timeframes": [
            {"timeframe": "1h", "bias": "SHORT"},
            {"timeframe": "2h", "bias": "SHORT"},
            {"timeframe": "4h", "bias": "SHORT"},
            {"timeframe": "1d", "bias": "SHORT"},
        ],
        "confirmation": {
            "trade_permission": "SHORT_ALLOWED",
            "stack_state": "ALIGNED",
            "confidence_penalty": 0,
        },
        "decision_chain": {
            "signal": {"signal": "WAIT"},
            "contradiction": {"trade_allowed": False},
            "risk": {"decision": "REJECT"},
            "executor": {"verdict": "BLOCKED"},
        },
    }

    penalty, blocks = _timeframe_stack_gate(
        context,
        "SHORT",
        enforce_decision_chain=False,
    )

    assert penalty == 0
    assert blocks == []
