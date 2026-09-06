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
