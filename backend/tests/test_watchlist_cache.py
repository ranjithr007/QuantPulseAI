from types import SimpleNamespace

from app.api.v1 import signals_api


def setup_function():
    signals_api._clear_watchlist_cache()


def teardown_function():
    signals_api._clear_watchlist_cache()


def test_shared_prediction_stack_defaults_to_intraday_execution_mode():
    assert (
        signals_api._mode_from_stack(signals_api.PREDICTION_TIMEFRAME_STACK)
        == "intraday"
    )


def test_watchlist_cache_reuses_payloads_and_returns_independent_copies(monkeypatch):
    symbols = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]
    build_calls = []

    monkeypatch.setattr(
        signals_api.SymbolRepository,
        "get_active_symbols",
        lambda self, db: symbols,
    )

    def build_payload(db, symbol, stack, stale_after_seconds):
        build_calls.append(symbol)
        return {"symbol": symbol, "trigger": {"status": "WAIT"}}

    monkeypatch.setattr(signals_api, "_build_entry_trigger_payload", build_payload)

    first_payloads, first_cache = signals_api._get_cached_watchlist_payloads(
        object(), ["5m", "15m", "1h"], 900
    )
    first_payloads[0]["trigger"]["status"] = "READY"
    second_payloads, second_cache = signals_api._get_cached_watchlist_payloads(
        object(), ["5m", "15m", "1h"], 900
    )

    assert build_calls == ["BTCUSDT", "ETHUSDT"]
    assert first_cache["hit"] is False
    assert second_cache["hit"] is True
    assert second_payloads[0]["trigger"]["status"] == "WAIT"


def test_watchlist_cache_separates_timeframe_stacks(monkeypatch):
    monkeypatch.setattr(
        signals_api.SymbolRepository,
        "get_active_symbols",
        lambda self, db: [SimpleNamespace(symbol="BTCUSDT")],
    )
    build_calls = []

    def build_payload(db, symbol, stack, stale_after_seconds):
        build_calls.append(tuple(stack))
        return {"symbol": symbol}

    monkeypatch.setattr(signals_api, "_build_entry_trigger_payload", build_payload)

    signals_api._get_cached_watchlist_payloads(object(), ["5m", "15m", "1h"], 900)
    signals_api._get_cached_watchlist_payloads(object(), ["15m", "1h", "4h"], 900)

    assert build_calls == [("5m", "15m", "1h"), ("15m", "1h", "4h")]


def test_watchlist_cache_expires_after_ttl(monkeypatch):
    clock = iter([100.0, 100.0, 100.0, 116.0, 116.0, 116.0])
    monkeypatch.setattr(signals_api.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        signals_api.SymbolRepository,
        "get_active_symbols",
        lambda self, db: [SimpleNamespace(symbol="BTCUSDT")],
    )
    build_calls = []

    def build_payload(db, symbol, stack, stale_after_seconds):
        build_calls.append(symbol)
        return {"symbol": symbol}

    monkeypatch.setattr(signals_api, "_build_entry_trigger_payload", build_payload)

    signals_api._get_cached_watchlist_payloads(object(), ["5m", "15m", "1h"], 900)
    payloads, cache = signals_api._get_cached_watchlist_payloads(
        object(), ["5m", "15m", "1h"], 900
    )

    assert payloads == [{"symbol": "BTCUSDT"}]
    assert cache["hit"] is False
    assert build_calls == ["BTCUSDT", "BTCUSDT"]


def test_watchlist_cache_bounds_distinct_parameter_sets(monkeypatch):
    monkeypatch.setattr(signals_api, "WATCHLIST_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(
        signals_api.SymbolRepository,
        "get_active_symbols",
        lambda self, db: [SimpleNamespace(symbol="BTCUSDT")],
    )
    monkeypatch.setattr(
        signals_api,
        "_build_entry_trigger_payload",
        lambda db, symbol, stack, stale_after_seconds: {"symbol": symbol},
    )

    signals_api._get_cached_watchlist_payloads(object(), ["1h"], 100)
    signals_api._get_cached_watchlist_payloads(object(), ["1h"], 200)
    signals_api._get_cached_watchlist_payloads(object(), ["1h"], 300)

    assert len(signals_api._watchlist_payload_cache) == 2
    assert (("1h",), 100) not in signals_api._watchlist_payload_cache
    assert signals_api._watchlist_cache_key_locks == {}
