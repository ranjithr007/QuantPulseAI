import pytest
from fastapi import HTTPException

from app.api.v1 import signals_api


def test_signal_batch_builds_each_normalized_symbol_once(monkeypatch):
    calls = []

    def build_payload(db, symbol, timeframe, stale_after_seconds):
        calls.append((symbol, timeframe, stale_after_seconds))
        return {"symbol": symbol, "signal": "WAIT"}

    monkeypatch.setattr(signals_api, "build_signal_payload", build_payload)

    payload = signals_api.build_signal_batch_payload(
        object(),
        [" btcusdt ", "ETHUSDT", "BTCUSDT"],
        "15m",
        1500,
    )

    assert calls == [("BTCUSDT", "15m", 1500), ("ETHUSDT", "15m", 1500)]
    assert payload["count"] == 2
    assert set(payload["records_by_symbol"]) == {"BTCUSDT", "ETHUSDT"}


def test_signal_batch_symbol_limit_is_enforced():
    with pytest.raises(HTTPException) as exc_info:
        signals_api._normalize_signal_batch_symbols(
            [f"SYMBOL{index}" for index in range(51)]
        )

    assert exc_info.value.status_code == 400


def test_signal_batch_summary_mode_uses_read_only_builder(monkeypatch):
    summary_calls = []

    def build_summary(db, symbol, timeframe, stale_after_seconds):
        summary_calls.append((symbol, timeframe, stale_after_seconds))
        return {"symbol": symbol, "signal": "WAIT"}

    def fail_full_payload(*args, **kwargs):
        raise AssertionError("summary batch must not build the write-heavy full payload")

    monkeypatch.setattr(signals_api, "build_signal_summary_payload", build_summary)
    monkeypatch.setattr(signals_api, "build_signal_payload", fail_full_payload)

    payload = signals_api.build_signal_batch_payload(
        object(),
        ["BTCUSDT", "ETHUSDT"],
        "1h",
        7200,
        summary_only=True,
    )

    assert summary_calls == [
        ("BTCUSDT", "1h", 7200),
        ("ETHUSDT", "1h", 7200),
    ]
    assert payload["count"] == 2
