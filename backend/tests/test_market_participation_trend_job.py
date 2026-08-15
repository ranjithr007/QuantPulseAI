from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.market_participation_trend_job import run_market_participation_trend_job


def _bullish_bars(timeframe):
    now = datetime(2026, 8, 15, 16, 0)
    rows = []
    for index in range(60):
        open_price = 100 + index * 0.25
        quote_volume = 200 if index == 59 else 100
        taker_buy = quote_volume * 0.72
        rows.append(
            {
                "timeframe": timeframe,
                "open_time": now - timedelta(hours=60 - index),
                "close_time": now - timedelta(hours=59 - index),
                "open": open_price,
                "high": open_price + 0.30,
                "low": open_price - 0.10,
                "close": open_price + 0.20,
                "quote_volume": quote_volume,
                "taker_buy_quote_volume": taker_buy,
                "taker_sell_quote_volume": quote_volume - taker_buy,
                "spot_delta_quote": (2 * taker_buy) - quote_volume,
                "is_final": True,
            }
        )
    return rows


def test_worker_calculates_and_persists_separate_trend_for_each_active_symbol():
    db = Mock()
    collector = Mock()
    collector.get_klines.side_effect = lambda _symbol, timeframe, limit: _bullish_bars(timeframe)
    symbol_repo = Mock()
    symbol_repo.get_active_symbols.return_value = [SimpleNamespace(symbol="BTCUSDT")]
    trend_repo = Mock()
    trend_repo.save.return_value = SimpleNamespace(id=7)

    with patch(
        "app.jobs.market_participation_trend_job.SessionLocal",
        return_value=db,
    ), patch(
        "app.jobs.market_participation_trend_job.SpotMarketCollector",
        return_value=collector,
    ), patch(
        "app.jobs.market_participation_trend_job.SymbolRepository",
        return_value=symbol_repo,
    ), patch(
        "app.jobs.market_participation_trend_job.MarketParticipationRepository",
        return_value=trend_repo,
    ), patch(
        "app.jobs.market_participation_trend_job._derivative_context",
        return_value={"funding_rate": 0.0001, "open_interest_change_percent": 1.0},
    ), patch(
        "app.jobs.market_participation_trend_job._liquidation_context",
        return_value={"data_quality": "OBSERVED", "bias": "HUNT_SHORTS"},
    ):
        result = run_market_participation_trend_job(
            context=SimpleNamespace(generation_id="test-generation")
        )

    assert result["status"] == "OK"
    assert result["count"] == 1
    assert result["records"][0]["direction"] == "BULLISH"
    saved = trend_repo.save.call_args.args[1]
    assert saved["source"] == "market_participation_trend_v1"
    assert saved["external_context"]["status"] == "UNAVAILABLE"
    assert trend_repo.save.call_args.kwargs["data_generation_id"] == "test-generation"
    db.close.assert_called_once_with()
