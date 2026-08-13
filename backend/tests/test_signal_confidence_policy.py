import pytest

from app.api.v1.risk_api import _build_auto_decision


def _decision(
    confidence,
    *,
    stack_state="ALIGNED",
    trade_permission="LONG_ALLOWED",
    legacy_penalty=0,
    selected_symbol="BTCUSDT",
    open_trades=None,
    account_risk=None,
):
    return _build_auto_decision(
        auto={
            "enabled": True,
            "locked": False,
            "emergencyStop": False,
            "allowedSymbols": ["BTCUSDT", "ETHUSDT"],
            "direction": "BOTH",
            "minConfidence": 40.0,
            "maxOpenTrades": 4,
            "dailyLossLimit": 4.0,
        },
        selected_symbol=selected_symbol,
        signal={
            "signal": "LONG",
            "confidence": confidence,
            "current_price": 100.0,
            "trade_plan": {"risk_reward": 2.0},
        },
        risk={"is_usable": True},
        computed_risk=None,
        paper_bundle={
            "openTrades": {"records": open_trades or []},
            "closedTrades": {"records": []},
            "accountRisk": account_risk,
        },
        multi_timeframe={
            "confirmation": {
                "stack_state": stack_state,
                "trade_permission": trade_permission,
                "confidence_penalty": legacy_penalty,
            }
        },
        derivatives={
            "availability": {"funding": True, "open_interest": True}
        },
    )


@pytest.mark.parametrize(
    ("confidence", "allowed"),
    [(39.99, False), (40.0, True), (40.01, True)],
)
def test_signal_confidence_entry_boundary(confidence, allowed):
    decision = _decision(confidence)

    assert decision["confidence"] == confidence
    assert decision["allowed"] is allowed
    assert ("Confidence below minimum" in decision["reasons"]) is (not allowed)


def test_legacy_timeframe_penalty_does_not_reduce_signal_confidence():
    decision = _decision(
        45.0,
        stack_state="MIXED_LIGHT",
        trade_permission="WAIT",
        legacy_penalty=15,
    )

    assert decision["confidence"] == 45.0
    assert decision["rawConfidence"] == 45.0
    assert "confidencePenalty" not in decision
    assert decision["allowed"] is True


def test_strong_timeframe_conflict_remains_a_separate_hard_block():
    decision = _decision(
        90.0,
        stack_state="MIXED_STRONG",
        trade_permission="WAIT",
        legacy_penalty=15,
    )

    assert decision["confidence"] == 90.0
    assert "confidencePenalty" not in decision
    assert decision["allowed"] is False
    assert "Higher timeframe conflict is too strong" in decision["reasons"]


def test_active_btc_trade_blocks_btc_but_not_another_coin():
    open_trades = [{"symbol": "BTCUSDT", "status": "OPEN"}]
    account_risk = {
        "daily_pnl_percent": -0.4,
        "daily_loss_limit_percent": 4.0,
        "limit_reached": False,
    }

    btc = _decision(80, open_trades=open_trades, account_risk=account_risk)
    eth = _decision(
        80,
        selected_symbol="ETHUSDT",
        open_trades=open_trades,
        account_risk=account_risk,
    )

    assert btc["allowed"] is False
    assert "Active trade already exists for this coin" in btc["coinBlockers"]
    assert eth["allowed"] is True
    assert eth["coinBlockers"] == []


def test_genuine_account_daily_loss_blocks_every_coin():
    account_risk = {
        "daily_pnl_percent": -4.0,
        "daily_loss_limit_percent": 4.0,
        "limit_reached": True,
    }

    btc = _decision(80, account_risk=account_risk)
    eth = _decision(80, selected_symbol="ETHUSDT", account_risk=account_risk)

    assert btc["allowed"] is False
    assert eth["allowed"] is False
    assert btc["accountBlockers"] == ["Account-wide daily loss limit reached"]
    assert eth["accountBlockers"] == ["Account-wide daily loss limit reached"]


def test_global_open_trade_cap_uses_account_count_not_selected_coin_records():
    decision = _decision(
        80,
        selected_symbol="ETHUSDT",
        open_trades=[],
        account_risk={
            "daily_pnl_percent": 0.0,
            "daily_loss_limit_percent": 4.0,
            "limit_reached": False,
            "open_trade_count": 4,
        },
    )

    assert decision["allowed"] is False
    assert decision["accountOpenTrades"] == 4
    assert decision["accountBlockers"] == ["Account-wide open trade cap reached"]
