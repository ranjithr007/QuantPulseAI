from types import SimpleNamespace

from app.features.trend_features import calculate_trend


def _candles(closes):
    return [SimpleNamespace(close_price=value) for value in closes]


def test_flat_momentum_is_neutral_on_zero_to_one_hundred_scale():
    result = calculate_trend(_candles([100.0] * 51))

    assert result["momentum_score"] == 50.0


def test_directional_momentum_is_symmetric_around_neutral():
    prefix = [100.0] * 45
    rising = prefix + [100.0, 100.4, 100.8, 101.2, 101.6, 102.0]
    falling = prefix + [100.0, 99.6, 99.2, 98.8, 98.4, 98.0]

    bullish = calculate_trend(_candles(rising))
    bearish = calculate_trend(_candles(falling))

    assert bullish["momentum_score"] == 60.0
    assert bearish["momentum_score"] == 40.0
