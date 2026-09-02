import json
from types import SimpleNamespace

from app.api.v1 import signals_api


STACK = ["1h", "2h", "4h", "1d"]


def _wait_payload(symbol="BTCUSDT"):
    return {
        "symbol": symbol,
        "mode": "intraday",
        "timeframes_used": list(STACK),
        "prediction_stack": list(STACK),
        "timeframes": [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "OK",
                "signal": "WAIT",
                "bias": "NEUTRAL",
                "direction": "NEUTRAL",
                "confidence": 20,
                "score": 20,
            }
            for timeframe in STACK
        ],
        "confirmation": {
            "overall_bias": "NEUTRAL",
            "trade_permission": "WAIT",
            "confidence": 20,
        },
        "trigger": {
            "status": "WAIT",
            "side": None,
            "reason": "Timeframes are mixed or neutral",
            "conditions": [],
        },
        "trade_plan": None,
        "trade_plan_validation": None,
    }


def test_http_watchlist_uses_persisted_read_model_not_inline_scan(monkeypatch):
    payload = _wait_payload()
    monkeypatch.setattr(
        signals_api,
        "_get_persisted_watchlist_payloads",
        lambda db, stack, stale_after_seconds: (
            [payload],
            {
                "hit": True,
                "source": "persisted_core_signal_snapshot",
                "age_seconds": 15,
                "ttl_seconds": 600,
                "missing_symbols": [],
                "stale_symbols": [],
            },
        ),
    )
    monkeypatch.setattr(
        signals_api,
        "_get_cached_watchlist_payloads",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("HTTP watchlist must not compute the governed stack inline")
        ),
    )
    monkeypatch.setattr(
        signals_api.RiskRepository,
        "latest_for_symbols",
        lambda self, db, symbols: {},
    )
    monkeypatch.setattr(
        signals_api.MarketParticipationRepository,
        "latest_for_symbols",
        lambda self, db, symbols: {},
    )

    result = signals_api.build_signal_watchlist_payload(
        object(),
        mode="intraday",
        stale_after_seconds=3900,
    )

    assert result["count"] == 1
    assert result["records"][0]["symbol"] == "BTCUSDT"
    assert result["records"][0]["status"] == "WAIT"
    assert result["cache"]["source"] == "persisted_core_signal_snapshot"


def test_core_snapshot_keeps_compact_watchlist_read_model():
    payload = _wait_payload()
    payload["timeframes"][0].update(
        {
            "freshness": {"status": "FRESH", "is_stale": False},
            "feature_trend": "BULLISH",
            "feature_trend_score": 65,
            "feature_momentum_score": 58,
            "price_return_pct": 3.25,
            "return_sample_size": 21,
        }
    )
    payload["unrelated_large_diagnostics"] = {"ignored": [1, 2, 3]}

    compact = signals_api._compact_watchlist_payload(payload)

    assert compact["prediction_stack"] == STACK
    assert [item["timeframe"] for item in compact["timeframes"]] == STACK
    assert compact["trigger"]["reason"] == "Timeframes are mixed or neutral"
    assert compact["timeframes"][0]["feature_trend"] == "BULLISH"
    assert compact["timeframes"][0]["feature_trend_score"] == 65
    assert compact["timeframes"][0]["price_return_pct"] == 3.25
    assert compact["timeframes"][0]["return_sample_size"] == 21
    assert compact["timeframes"][0]["freshness"]["is_stale"] is False
    assert "unrelated_large_diagnostics" not in compact


def test_snapshot_read_model_is_loaded_from_decision_context():
    payload = _wait_payload()
    snapshot = SimpleNamespace(
        snapshot_json=json.dumps(
            {"context": {"watchlist_payload": payload}}
        )
    )

    restored = signals_api._watchlist_payload_from_snapshot(snapshot)
    restored["trigger"]["status"] = "READY"

    assert payload["trigger"]["status"] == "WAIT"


def test_stale_snapshot_fails_closed_without_reusing_old_plan():
    payload = _wait_payload()
    payload["trigger"] = {
        "status": "READY",
        "side": "LONG",
        "reason": "All gates passed",
        "conditions": [],
    }
    payload["trade_plan"] = {
        "entry": 100,
        "stop_loss": 99.25,
        "target1": 101.5,
        "target2": 102.3,
    }

    stale = signals_api._stale_watchlist_payload(payload)

    assert stale["trigger"]["status"] == "WAIT"
    assert stale["trigger"]["side"] is None
    assert stale["trade_plan"] is None
    assert stale["trade_plan_validation"]["is_valid"] is False
    assert all(item["status"] == "STALE" for item in stale["timeframes"])
    assert all(item["freshness"]["is_stale"] for item in stale["timeframes"])
    assert payload["trigger"]["status"] == "READY"


def test_return_profile_uses_twenty_complete_bar_intervals():
    candles = [SimpleNamespace(close_price=100 + index) for index in range(21)]

    profile = signals_api._return_profile(candles)

    assert profile == {"return_pct": 20.0, "sample_size": 21}


def test_return_profile_requires_complete_history():
    candles = [SimpleNamespace(close_price=100 + index) for index in range(20)]

    profile = signals_api._return_profile(candles)

    assert profile == {"return_pct": None, "sample_size": 20}
