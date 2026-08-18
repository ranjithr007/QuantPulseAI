from datetime import datetime, timedelta, timezone

from app.api.v1.paper_trade_api import _market_participation_blockers
from app.collectors.binances.spot_market_collector import SpotMarketCollector
from app.intelligence.market_participation_trend_engine import analyze_spot_stack
from app.intelligence.market_participation_trend_engine import build_market_breadth
from app.intelligence.market_participation_trend_engine import build_market_participation_trend
from app.intelligence.market_participation_trend_engine import find_dynamic_price_zones


NOW = datetime(2026, 8, 15, 16, 0)


def _bars(*, bullish=True, count=60, timeframe="1h"):
    result = []
    base = 100.0
    step = 0.25 if bullish else -0.25
    for index in range(count):
        open_price = base + step * index
        close_price = open_price + (0.20 if bullish else -0.20)
        quote_volume = 200.0 if index == count - 1 else 100.0
        taker_buy = quote_volume * (0.72 if bullish else 0.28)
        result.append(
            {
                "symbol": "BTCUSDT",
                "timeframe": timeframe,
                "open_time": NOW - timedelta(hours=count - index),
                "close_time": NOW - timedelta(hours=count - index - 1),
                "open": open_price,
                "high": max(open_price, close_price) + 0.10,
                "low": min(open_price, close_price) - 0.10,
                "close": close_price,
                "quote_volume": quote_volume,
                "taker_buy_quote_volume": taker_buy,
                "taker_sell_quote_volume": quote_volume - taker_buy,
                "spot_delta_quote": (2 * taker_buy) - quote_volume,
                "is_final": True,
            }
        )
    return result


def _stack(bullish=True):
    return analyze_spot_stack(
        "BTCUSDT",
        {
            timeframe: _bars(bullish=bullish, timeframe=timeframe)
            for timeframe in ("1h", "2h", "4h", "1d")
        },
    )


def test_bullish_spot_participation_produces_separate_executable_long_trend():
    spot = _stack(bullish=True)
    breadth = build_market_breadth({"BTCUSDT": spot, "ETHUSDT": spot})

    result = build_market_participation_trend(
        spot,
        derivatives={
            "funding_rate": 0.0001,
            "open_interest_change_percent": 1.5,
        },
        breadth=breadth,
        ethbtc={"status": "READY", "score": 40},
        liquidation={"data_quality": "OBSERVED", "bias": "HUNT_SHORTS"},
    )

    assert result["status"] == "READY"
    assert result["direction"] == "BULLISH"
    assert result["execution_side"] == "LONG"
    assert result["confidence"] >= 40
    assert result["external_context"]["status"] == "UNAVAILABLE"


def test_bearish_spot_participation_produces_separate_executable_short_trend():
    spot = _stack(bullish=False)

    result = build_market_participation_trend(
        spot,
        derivatives={
            "funding_rate": 0.0007,
            "open_interest_change_percent": 2.0,
        },
        breadth={
            "status": "READY",
            "bullish_percent": 0,
            "bearish_percent": 100,
        },
        ethbtc={"status": "READY", "score": -40},
        liquidation={"data_quality": "OBSERVED", "bias": "HUNT_LONGS"},
    )

    assert result["direction"] == "BEARISH"
    assert result["execution_side"] == "SHORT"
    assert result["confidence"] >= 40


def test_missing_spot_timeframes_fail_closed():
    spot = analyze_spot_stack("BTCUSDT", {"1h": _bars()})
    result = build_market_participation_trend(spot)

    assert result["status"] == "DEGRADED"
    assert result["quality_state"] == "DEGRADED"


def test_timeframe_evidence_exposes_auditable_score_components():
    timeframe = analyze_spot_stack("BTCUSDT", {"1h": _bars(bullish=True)})[
        "timeframes"
    ][0]

    components = timeframe["score_components"]

    assert components["ema"] == 12.0
    assert components["cvd"] > 0
    assert components["price_change"] > 0
    assert components["relative_volume"] > 0
    assert components["total"] == timeframe["score"]
    assert set(components) == {
        "ema",
        "cvd",
        "price_change",
        "relative_volume",
        "resistance",
        "support",
        "total",
    }


def test_paper_entry_requires_fresh_matching_market_participation_direction():
    bullish = {
        "status": "READY",
        "quality_state": "OK",
        "direction": "BULLISH",
        "confidence": 62,
        "effective_timestamp": datetime.utcnow(),
    }
    assert _market_participation_blockers(bullish, "LONG") == []
    assert "SHORT requires BEARISH" in _market_participation_blockers(
        bullish,
        "SHORT",
    )[0]

    stale = {**bullish, "effective_timestamp": datetime.utcnow() - timedelta(hours=2)}
    assert _market_participation_blockers(stale, "LONG") == [
        "Market participation trend is stale"
    ]


def test_spot_collector_uses_exchange_taker_buy_volume_for_real_delta():
    now = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)
    rows = [
        [
            int((now - timedelta(hours=2)).timestamp() * 1000),
            "100",
            "102",
            "99",
            "101",
            "10",
            int((now - timedelta(hours=1)).timestamp() * 1000),
            "1000",
            120,
            "6",
            "650",
            "0",
        ],
        [
            int((now - timedelta(minutes=30)).timestamp() * 1000),
            "101",
            "103",
            "100",
            "102",
            "8",
            int((now + timedelta(minutes=30)).timestamp() * 1000),
            "800",
            80,
            "4",
            "400",
            "0",
        ],
    ]

    parsed = SpotMarketCollector._parse_final_klines(
        rows,
        "BTCUSDT",
        "1h",
        now=now,
    )

    assert len(parsed) == 1
    assert parsed[0]["taker_buy_quote_volume"] == 650
    assert parsed[0]["taker_sell_quote_volume"] == 350
    assert parsed[0]["spot_delta_quote"] == 300


def test_dynamic_resistance_requires_repeated_historical_tests_for_rejection():
    bars = _bars(count=35)
    for index in range(len(bars)):
        bars[index].update({"open": 104.0, "high": 106.0 + index * 0.01, "low": 103.0, "close": 105.0})
    bars[10]["high"] = 110.0
    bars[20]["high"] = 110.0
    bars[-1].update({"open": 106.0, "high": 110.1, "low": 104.0, "close": 105.0})

    zones = find_dynamic_price_zones(bars)

    assert zones["resistance"]["tests"] == 2
    assert zones["resistance"]["latest_rejected"] is True
