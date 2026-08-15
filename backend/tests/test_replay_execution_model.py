from types import SimpleNamespace

import pytest

from app.api.v1 import backtest_api
from app.backtesting.filtered_replay_engine import FilteredReplayConfig
from app.backtesting.filtered_replay_engine import _entry_exit_levels
from app.backtesting.filtered_replay_engine import _execution_confidence
from app.backtesting.filtered_replay_engine import _exit_trigger_with_policy
from app.backtesting.filtered_replay_engine import _liquidation_diagnostics
from app.backtesting.filtered_replay_engine import _position_sizing
from app.backtesting.filtered_replay_engine import _portfolio_gate
from app.backtesting.filtered_replay_engine import _portfolio_state
from app.backtesting.filtered_replay_engine import _replay_funding_rate
from app.backtesting.trade_simulator import build_collision_sensitivity_report


def _candle(*, open_price=100, high_price=104, low_price=96, close_price=101):
    return SimpleNamespace(
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
    )


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("STOP_FIRST", ("STOP", 98)),
        ("TARGET_FIRST", ("TARGET", 103)),
        ("LOWER_TIMEFRAME_REQUIRED", ("AMBIGUOUS_COLLISION", 98)),
    ],
)
def test_intrabar_collision_policy_is_explicit(policy, expected):
    assert _exit_trigger_with_policy(_candle(), "LONG", 98, 103, policy) == expected


def test_fixed_risk_sizing_respects_notional_cap():
    uncapped = _position_sizing(
        capital=10_000,
        entry=100,
        stop_distance=2,
        position_size_percent=100,
        max_leverage=1,
        risk_percent_per_trade=1,
    )
    capped = _position_sizing(
        capital=10_000,
        entry=100,
        stop_distance=2,
        position_size_percent=100,
        max_leverage=1,
        risk_percent_per_trade=5,
    )

    assert uncapped["mode"] == "FIXED_RISK_CAPPED"
    assert uncapped["quantity"] == pytest.approx(50)
    assert uncapped["planned_risk_amount"] == pytest.approx(100)
    assert capped["quantity"] == pytest.approx(100)
    assert capped["notional"] == pytest.approx(capped["notional_cap"])


def test_capital_percent_sizing_preserves_configured_leverage():
    sizing = _position_sizing(
        capital=10_000,
        entry=100,
        stop_distance=2,
        position_size_percent=50,
        max_leverage=3,
        risk_percent_per_trade=None,
    )

    assert sizing["mode"] == "CAPITAL_PERCENT"
    assert sizing["notional"] == pytest.approx(15_000)
    assert sizing["allocated_capital"] == pytest.approx(5_000)
    assert sizing["effective_leverage"] == pytest.approx(1.5)


def test_volatility_targeted_sizing_is_capped_by_notional_limit():
    sizing = _position_sizing(
        capital=10_000,
        entry=100,
        stop_distance=2,
        position_size_percent=100,
        max_leverage=2,
        risk_percent_per_trade=None,
        target_trade_volatility_percent=1,
        atr=0.25,
    )

    assert sizing["mode"] == "VOLATILITY_TARGETED_CAPPED"
    assert sizing["quantity"] == pytest.approx(200)
    assert sizing["notional"] == pytest.approx(20_000)
    assert sizing["notional"] == sizing["notional_cap"]


def test_portfolio_gate_uses_pre_decision_open_positions_and_gross_exposure():
    state = _portfolio_state(
        [{"symbol": "BTCUSDT", "side": "LONG", "notional": 4_000}],
        10_000,
    )
    allowed = _portfolio_gate(
        state,
        side="SHORT",
        candidate_notional=3_000,
        capital=10_000,
        max_open_positions=3,
        max_gross_exposure_percent=80,
    )
    blocked = _portfolio_gate(
        state,
        side="LONG",
        candidate_notional=5_000,
        capital=10_000,
        max_open_positions=3,
        max_gross_exposure_percent=80,
    )

    assert allowed["allowed"] is True
    assert allowed["projected_state"]["open_positions"] == 2
    assert allowed["projected_state"]["net_exposure"] == pytest.approx(1_000)
    assert blocked["allowed"] is False
    assert blocked["reason"] == "PORTFOLIO_MAX_GROSS_EXPOSURE"


def test_replay_config_rejects_two_sizing_authorities():
    with pytest.raises(ValueError, match="mutually exclusive"):
        FilteredReplayConfig(
            risk_percent_per_trade=1,
            target_trade_volatility_percent=1,
        )


def test_paper_policy_replay_uses_fixed_five_percent_stop_and_cost_adjusted_2r():
    config = FilteredReplayConfig(
        stop_atr_multiple=5,
        target_atr_multiple=10,
        exit_distance_model="PAPER_POLICY",
    )

    long_stop, long_target, long_risk, long_reward = _entry_exit_levels(
        "LONG",
        100,
        2,
        50,
        config,
    )
    short_stop, short_target, short_risk, short_reward = _entry_exit_levels(
        "SHORT",
        100,
        2,
        50,
        config,
    )

    assert long_stop == pytest.approx(95)
    assert short_stop == pytest.approx(105)
    assert long_target > 110
    assert short_target < 90
    assert long_risk == pytest.approx(5)
    assert short_risk == pytest.approx(5)
    assert long_reward > 10
    assert short_reward > 10


def test_replay_config_rejects_unknown_exit_distance_model():
    with pytest.raises(ValueError, match="exit_distance_model"):
        FilteredReplayConfig(exit_distance_model="UNKNOWN")


def test_replay_sizing_uses_governed_entry_confidence_over_composite_confidence():
    decision = {
        "confidence": 74.5,
        "timeframe_stack": {
            "decision_chain": {
                "signal": {"confidence": 49.0},
                "risk": {"confidence": 49.0},
            }
        },
    }

    assert _execution_confidence(decision) == 49.0


def test_backtest_api_rejects_two_sizing_authorities():
    with pytest.raises(Exception) as error:
        backtest_api.collision_sensitivity_report(
            symbol="DOGEUSDT",
            signal="SHORT",
            timeframe="1h",
            risk_percent_per_trade=1,
            target_trade_volatility_percent=1,
        )

    assert error.value.status_code == 422


def test_funding_rate_uses_frozen_derivatives_payload():
    stack = {"derivatives": {"funding": {"rate": "0.0001"}}}

    assert _replay_funding_rate(stack) == pytest.approx(0.0001)
    assert _replay_funding_rate({}) == 0


def test_liquidation_diagnostic_uses_candle_extremes():
    no_leverage = _liquidation_diagnostics(
        [_candle(low_price=50)],
        "LONG",
        100,
        100,
        10_000,
        0.005,
    )
    leveraged = _liquidation_diagnostics(
        [_candle(low_price=80)],
        "LONG",
        100,
        500,
        10_000,
        0.005,
    )

    assert no_leverage["price"] is None
    assert no_leverage["touched"] is False
    assert leveraged["price"] == pytest.approx(80.40201005)
    assert leveraged["touched"] is True


def test_liquidation_uses_matching_exchange_margin_tier_and_mark_prices():
    diagnostics = _liquidation_diagnostics(
        [_candle(low_price=80.0)],
        "LONG",
        100,
        500,
        10_000,
        0.005,
        maintenance_margin_brackets=(
            {
                "bracket": 1,
                "notional_floor": 0,
                "notional_cap": 10_000,
                "maintenance_margin_rate": 0.004,
                "maintenance_amount": 0,
                "source": "BINANCE_ACCOUNT_SNAPSHOT",
            },
            {
                "bracket": 2,
                "notional_floor": 10_000,
                "notional_cap": 250_000,
                "maintenance_margin_rate": 0.0065,
                "maintenance_amount": 250,
                "source": "BINANCE_ACCOUNT_SNAPSHOT",
            },
        ),
        price_source="HISTORICAL_MARK_PRICE_KLINES",
    )

    assert diagnostics["margin_bracket"]["bracket"] == 2
    assert diagnostics["maintenance_margin_rate"] == pytest.approx(0.0065)
    assert diagnostics["maintenance_amount"] == pytest.approx(250)
    assert diagnostics["price_source"] == "HISTORICAL_MARK_PRICE_KLINES"
    assert diagnostics["touched"] is True


def test_unknown_collision_policy_is_rejected():
    with pytest.raises(ValueError, match="collision_policy"):
        FilteredReplayConfig(collision_policy="UNKNOWN")


def test_collision_sensitivity_report_compares_against_conservative_baseline():
    report = build_collision_sensitivity_report(
        {
            "STOP_FIRST": {
                "total_trades": 2,
                "wins": 1,
                "losses": 1,
                "total_return_percent": -1,
                "trades": [{"intrabar_collision": True, "exit_reason": "STOP"}],
            },
            "TARGET_FIRST": {
                "total_trades": 2,
                "wins": 2,
                "losses": 0,
                "total_return_percent": 3,
                "trades": [{"intrabar_collision": True, "exit_reason": "TARGET"}],
            },
            "LOWER_TIMEFRAME_REQUIRED": {
                "total_trades": 2,
                "wins": 1,
                "losses": 1,
                "total_return_percent": -1,
                "trades": [
                    {
                        "intrabar_collision": True,
                        "exit_reason": "AMBIGUOUS_COLLISION",
                    }
                ],
            },
        }
    )

    policies = {item["policy"]: item for item in report["policies"]}
    assert report["baseline_policy"] == "STOP_FIRST"
    assert report["production_policy_unchanged"] is True
    assert report["research_only"] is True
    assert report["sensitivity"]["return_range_percent"] == 4
    assert report["sensitivity"]["outcome_sensitive"] is True
    assert policies["TARGET_FIRST"]["return_delta_vs_stop_first"] == 4
    assert policies["LOWER_TIMEFRAME_REQUIRED"]["ambiguous_collision_exits"] == 1


def test_collision_sensitivity_api_forwards_research_controls(monkeypatch):
    captured = {}

    def execute(symbol, timeframe, signal, **options):
        captured.update(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": signal,
                **options,
            }
        )
        return {"baseline_policy": "STOP_FIRST", "policies": []}

    monkeypatch.setattr(
        backtest_api,
        "execute_collision_sensitivity_backtest",
        execute,
    )
    response = backtest_api.collision_sensitivity_report(
        symbol="DOGEUSDT",
        signal="SHORT",
        timeframe="1h",
        limit=800,
        initial_capital=20_000,
        position_size_percent=50,
        min_confidence=65,
        stop_atr_multiple=1.5,
        target_atr_multiple=3.5,
        cooldown_candles=4,
        fee_bps=5,
        slippage_bps=3,
        risk_percent_per_trade=1,
        target_trade_volatility_percent=None,
        max_leverage=3,
        max_open_positions=5,
        max_gross_exposure_percent=250,
        initial_portfolio_json="[]",
    )

    assert response["source"] == "collision_sensitivity_v1"
    assert response["result"]["baseline_policy"] == "STOP_FIRST"
    assert captured == {
        "symbol": "DOGEUSDT",
        "timeframe": "1h",
        "signal": "SHORT",
        "limit": 800,
        "initial_capital": 20_000,
        "position_size_percent": 50,
        "min_confidence": 65,
        "stop_atr_multiple": 1.5,
        "target_atr_multiple": 3.5,
        "cooldown_candles": 4,
        "fee_bps": 5,
        "slippage_bps": 3,
        "risk_percent_per_trade": 1,
        "target_trade_volatility_percent": None,
        "max_leverage": 3,
        "max_open_positions": 5,
        "max_gross_exposure_percent": 250,
        "initial_portfolio_positions": [],
    }
