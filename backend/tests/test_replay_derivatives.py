from datetime import datetime, timedelta, timezone

from app.backtesting.replay_derivatives import build_derivatives_as_of


def test_replay_derivatives_excludes_future_exchange_events():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mark_prices = [
        {
            "open_price": 100,
            "high_price": 105,
            "low_price": 98,
            "close_price": 102,
            "close_time": base + timedelta(hours=1),
            "source": "BINANCE_MARK_PRICE_KLINES",
        },
        {
            "open_price": 102,
            "high_price": 110,
            "low_price": 101,
            "close_price": 109,
            "close_time": base + timedelta(hours=20),
        },
    ]
    margin_brackets = [
        {
            "snapshot_version": "old",
            "effective_at": base,
            "bracket_number": 1,
            "notional_floor": 0,
            "notional_cap": 10_000,
            "initial_leverage": 50,
            "maintenance_margin_rate": 0.01,
            "maintenance_amount": 0,
            "source": "BINANCE_LEVERAGE_BRACKET",
        },
        {
            "snapshot_version": "future",
            "effective_at": base + timedelta(hours=12),
            "bracket_number": 1,
            "notional_floor": 0,
            "notional_cap": 10_000,
            "initial_leverage": 25,
            "maintenance_margin_rate": 0.02,
            "maintenance_amount": 0,
        },
    ]
    result = build_derivatives_as_of(
        [
            {"rate": 0.0001, "funding_time": base},
            {"rate": 0.0003, "funding_time": base + timedelta(hours=16)},
        ],
        [
            {"value": 1000, "timestamp": base + timedelta(hours=1)},
            {"value": 1100, "timestamp": base + timedelta(hours=2)},
            {"value": 9000, "timestamp": base + timedelta(hours=12)},
        ],
        base + timedelta(hours=3),
        mark_price_records=mark_prices,
        margin_bracket_records=margin_brackets,
    )

    assert result["status"] == "READY"
    assert result["funding"]["rate"] == 0.0001
    assert result["open_interest"]["value"] == 1100
    assert result["open_interest"]["change_pct"] == 10.0
    assert result["availability"]["mark_price"] is True
    assert result["mark_price"]["close"] == 102
    assert result["mark_price"]["source"] == "BINANCE_MARK_PRICE_KLINES"
    assert result["margin_brackets"]["snapshot_version"] == "old"
    assert result["margin_brackets"]["brackets"][0]["max_leverage"] == 50
    assert result["leakage_status"] == "PASS"


def test_replay_derivatives_reports_partial_and_stale_against_replay_clock():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = build_derivatives_as_of(
        [{"rate": -0.0002, "funding_time": base}],
        [],
        base + timedelta(hours=13),
        funding_stale_after_seconds=43_200,
    )

    assert result["status"] == "PARTIAL"
    assert result["availability"] == {
        "funding": True,
        "open_interest": False,
        "mark_price": False,
        "margin_brackets": False,
    }
    assert result["funding"]["freshness"] == "STALE"
    assert result["open_interest"]["freshness"] == "UNAVAILABLE"
