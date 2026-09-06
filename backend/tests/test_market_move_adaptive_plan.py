from datetime import datetime, timezone

import pytest

from app.api.v1.signals_api import _build_market_move_strategy_payload
from app.api.v1.paper_trade_api import _rebase_paper_trade_candidate
from app.intelligence.market_participation_trend_engine import analyze_spot_timeframe


def payload(side, atr=2.0):
    return {
        "status": "READY", "quality_state": "OK",
        "direction": "BULLISH" if side == "LONG" else "BEARISH",
        "confidence": 64, "effective_timestamp": datetime.now(timezone.utc),
        "spot": {"timeframes": [
            {"timeframe": timeframe, "status": "READY",
             "score": score if side == "LONG" else -score,
             "spot_price": 100, "atr": value,
             "support": {"lower": 97}, "resistance": {"upper": 103}}
            for timeframe, score, value in [("1h", 60, atr), ("4h", 45, 20)]
        ]},
    }


@pytest.mark.parametrize("side,stop", [("LONG", 96.5), ("SHORT", 103.5)])
def test_plan_uses_selected_timeframe_volatility_and_structure(side, stop):
    result = _build_market_move_strategy_payload({"symbol": "ETHUSDT"}, payload(side))
    plan = result["trade_plan"]
    assert result["trigger"]["status"] == "READY"
    assert result["trigger"]["entry_timeframe"] == "1h"
    assert plan["atr"] == 2
    assert plan["stop_loss"] == stop
    assert plan["exit_policy"] == "PAPER_ATR_STRUCTURE_V1"
    assert plan["target1_net_risk_reward"] >= 1.5
    assert plan["target2_net_risk_reward"] >= 2.3
    assert (plan["target2"] > plan["target1"] > 100) if side == "LONG" else (plan["target2"] < plan["target1"] < 100)


@pytest.mark.parametrize("atr", [None, 0, -1, "bad", float("nan"), float("inf")])
def test_missing_selected_atr_does_not_borrow_other_timeframe_or_invent_volatility(atr):
    result = _build_market_move_strategy_payload({"symbol": "ETHUSDT"}, payload("LONG", atr))
    assert result["trade_plan"] is None
    assert result["trigger"]["status"] == "WAIT"
    assert "ATR is unavailable" in result["trigger"]["reason"]


def test_spot_atr_includes_gaps_and_excludes_unfinished_candles():
    bars = [{"open": 100, "close": 100, "high": 101, "low": 99} for _ in range(60)]
    bars[-1] = {"open": 110, "close": 110, "high": 111, "low": 109}
    bars.append({"close": 999, "high": 1000, "low": 1, "is_final": False})
    result = analyze_spot_timeframe("ETHUSDT", "1h", bars)
    assert result["atr"] == pytest.approx((19 * 2 + 11) / 20)
    assert result["spot_price"] == 110


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_market_move_adaptive_stop_survives_actual_entry_repricing(side):
    plan = _build_market_move_strategy_payload(
        {"symbol": "ETHUSDT"}, payload(side)
    )["trade_plan"]
    candidate = {
        "symbol": "ETHUSDT", "side": side,
        "trade_plan": {**plan, "entry_price": plan["entry"], "entry_timeframe": "1h"},
        "risk_decision": {"confidence": 64, "risk_percent": 1},
        "fill_profile": {"fee_bps": 7.5},
    }
    result, error = _rebase_paper_trade_candidate(candidate, {
        "mark_price": 105, "observed_at": datetime.now(timezone.utc),
        "source": "TEST_MARK",
    })
    assert error is None
    risk = result["execution_risk"]
    entry = result["fill_profile"]["entry_fill_price"]
    assert entry != plan["entry"]
    assert risk["decision"] == "APPROVE"
    assert abs(entry - risk["stop_loss"]) / entry == pytest.approx(0.035, abs=0.0001)
    assert risk["risk_reward"] >= 2
    if side == "LONG":
        assert risk["stop_loss"] < entry < risk["target1"] < risk["target2"]
    else:
        assert risk["stop_loss"] > entry > risk["target1"] > risk["target2"]
    assert candidate["trade_plan"]["entry_price"] == 100
