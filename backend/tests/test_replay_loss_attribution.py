from types import SimpleNamespace

from app.backtesting.filtered_replay_engine import (
    _excursion_metrics,
    _intrabar_collision,
    _loss_classification,
)


def _candle(high, low, close=100):
    return SimpleNamespace(
        high_price=high,
        low_price=low,
        close_price=close,
    )


def test_excursion_metrics_capture_post_stop_target_recovery():
    candles = [
        _candle(101, 99),
        _candle(101.5, 97.5),
        _candle(104.5, 99),
    ]

    metrics = _excursion_metrics(
        candles,
        0,
        1,
        "LONG",
        100,
        98,
        104,
    )

    assert metrics["mfe_r"] == 0.75
    assert metrics["mae_r"] == 1.25
    assert metrics["post_stop_target_recovered"] is True
    assert (
        _loss_classification("LOSS", "STOP_LOSS", metrics)
        == "STOP_TOO_TIGHT_OR_ENTRY_EARLY"
    )


def test_loss_classifies_immediate_wrong_direction():
    metrics = {
        "mfe_r": 0.1,
        "mae_r": 1.0,
        "post_stop_target_recovered": False,
    }

    assert (
        _loss_classification("LOSS", "STOP_LOSS", metrics)
        == "IMMEDIATE_WRONG_DIRECTION"
    )


def test_intrabar_collision_detects_both_stop_and_target():
    candle = _candle(105, 95)

    assert _intrabar_collision(candle, "LONG", 98, 104) is True
    assert _intrabar_collision(candle, "SHORT", 102, 96) is True
