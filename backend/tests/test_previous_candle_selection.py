from types import SimpleNamespace

from app.intelligence import contradiction_engine
from app.intelligence import probability_engine


def test_probability_engine_uses_penultimate_candle(monkeypatch):
    candles = [
        SimpleNamespace(close_price=100),
        SimpleNamespace(close_price=102),
        SimpleNamespace(close_price=105),
    ]
    monkeypatch.setattr(probability_engine, "get_latest_candles", lambda *args, **kwargs: candles)

    assert probability_engine._previous_candle(object(), "BTCUSDT", "1h") is candles[-2]


def test_contradiction_engine_uses_penultimate_candle(monkeypatch):
    candles = [
        SimpleNamespace(close_price=100),
        SimpleNamespace(close_price=102),
        SimpleNamespace(close_price=105),
    ]
    monkeypatch.setattr(contradiction_engine, "get_latest_candles", lambda *args, **kwargs: candles)

    assert contradiction_engine._previous_candle(object(), "BTCUSDT", "1h") is candles[-2]
