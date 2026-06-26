from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from app.intelligence.contradiction_engine import build_contradiction_report
from app.intelligence.probability_engine import build_probability_profile
from app.observability.performance_budget import build_stage_latency_report
from app.observability.performance_budget import summarize_latency_samples


def test_summarize_latency_samples_computes_percentiles_and_budget_state():
    summary = summarize_latency_samples([10, 20, 30, 40, 50])

    assert summary["sample_count"] == 5
    assert summary["min_ms"] == 10
    assert summary["max_ms"] == 50
    assert summary["p50_ms"] == 30
    assert summary["p95_ms"] == 48
    assert summary["p99_ms"] == 49.6
    assert summary["budget_passed"] is True


def test_build_stage_latency_report_uses_each_stage_callable(monkeypatch):
    calls = []

    def fake_measure(operation, sample_size=5):
        calls.append(operation())
        return [10, 20, 30]

    monkeypatch.setattr(
        "app.observability.performance_budget.measure_callable",
        fake_measure,
    )

    report = build_stage_latency_report(
        {
            "watchlist": lambda: "watchlist",
            "risk": lambda: "risk",
        },
        sample_size=3,
    )

    assert calls == ["watchlist", "risk"]
    assert report["sample_size"] == 3
    assert report["stages"]["watchlist"]["p50_ms"] == 20
    assert report["stages"]["risk"]["sample_count"] == 3


def test_contradiction_report_is_cached_per_session():
    db = SimpleNamespace(info={})
    candle = None

    with patch(
        "app.intelligence.contradiction_engine.get_latest_candle",
        return_value=candle,
    ) as get_latest_candle:
        first = build_contradiction_report(db, "BTCUSDT", "5m", 900)
        second = build_contradiction_report(db, "BTCUSDT", "5m", 900)

    assert get_latest_candle.call_count == 1
    assert first == second
    assert first is not second


def test_probability_profile_is_cached_per_session():
    db = SimpleNamespace(info={})

    with patch(
        "app.intelligence.probability_engine.get_latest_candle",
        return_value=None,
    ) as get_latest_candle, patch(
        "app.intelligence.probability_engine.build_contradiction_report",
        return_value={"status": "INVALIDATED"},
    ) as build_report:
        first = build_probability_profile(db, "BTCUSDT", "5m", 900)
        second = build_probability_profile(db, "BTCUSDT", "5m", 900)

    assert get_latest_candle.call_count == 1
    assert build_report.call_count == 1
    assert first == second
    assert first is not second

