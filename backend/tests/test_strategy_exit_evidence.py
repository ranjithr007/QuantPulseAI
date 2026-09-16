from app.api.v1.strategy_api import _compact_learning_evaluation
from app.api.v1.strategy_api import _strategy_paper_trade_payload
from app.database.models.strategy_shadow_trade import StrategyShadowTrade


def test_payload_exposes_actual_policy_not_trailing_stop_inference():
    trade = StrategyShadowTrade(id=1, symbol="SOLUSDT", side="LONG", entry_price=100,
                                initial_stop_loss=99.25, stop_loss=102, exit_policy="PAPER_ATR_STRUCTURE_V1",
                                strategy_id="MARKET_MOVE", strategy_version="market_move_v1")
    result = _strategy_paper_trade_payload(trade)
    assert result["recorded_exit_policy"] == "PAPER_ATR_STRUCTURE_V1"
    assert result["recorded_initial_stop_loss"] == 99.25
    assert result["stop_loss"] == 102


def test_missing_policy_is_not_substituted():
    result = _strategy_paper_trade_payload(StrategyShadowTrade(id=1, stop_loss=99))
    assert result["recorded_exit_policy"] is None
    assert result["recorded_initial_stop_loss"] is None


def test_compact_payload_excludes_heavy_audit_evidence():
    trade = StrategyShadowTrade(
        id=1,
        symbol="SOLUSDT",
        side="LONG",
        entry_price=100,
        stop_loss=99,
        execution_evidence_json='{"release_version":"test"}',
        exit_evidence_json='{"classification":"INITIAL_STOP"}',
    )

    result = _strategy_paper_trade_payload(trade, include_evidence=False)

    assert result["audit_evidence_included"] is False
    assert result["exit_classification"] == "INITIAL_STOP"
    assert "execution_evidence" not in result
    assert "exit_evidence" not in result


def test_compact_learning_evaluation_keeps_dashboard_direction_breakdown():
    result = _compact_learning_evaluation({
        "status": "COLLECTING",
        "diagnostics": {
            "by_side": {"LONG": {"closed_trades": 2}},
            "by_symbol": {"SOLUSDT": {"closed_trades": 2}},
            "by_timeframe": {"1H": {"closed_trades": 2}},
        },
    })

    assert result["status"] == "COLLECTING"
    assert result["diagnostics_compact"] is True
    assert result["diagnostics"] == {
        "by_side": {"LONG": {"closed_trades": 2}},
    }
