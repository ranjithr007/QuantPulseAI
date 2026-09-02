from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.database.models.liquidations import Liquidation
from app.engines.liquidation_heatmap_engine import LiquidationHeatmapEngine
from app.jobs.market_participation_trend_job import _derivative_context
from app.jobs.market_participation_trend_job import _liquidation_context
from app.jobs.market_participation_trend_job import run_market_participation_trend_job
from app.repositories.heatmap_repository import HeatmapRepository


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
    fred_collector = Mock()
    fred_collector.collect.return_value = {
        "status": "VERIFIED",
        "provider": "FRED",
        "macro_score": 35.0,
        "series_count": 8,
        "data_timestamp": "2026-08-15",
        "advisory_only": True,
    }
    spot_repo = Mock()
    spot_repo.save_many.return_value = 1680

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
        "app.jobs.market_participation_trend_job.SpotMarketRepository",
        return_value=spot_repo,
    ), patch(
        "app.jobs.market_participation_trend_job._derivative_context",
        return_value={"funding_rate": 0.0001, "open_interest_change_percent": 1.0},
    ), patch(
        "app.jobs.market_participation_trend_job._liquidation_context",
        return_value={"data_quality": "OBSERVED", "bias": "HUNT_SHORTS"},
    ), patch(
        "app.jobs.market_participation_trend_job.FredMacroCollector",
        return_value=fred_collector,
    ):
        result = run_market_participation_trend_job(
            context=SimpleNamespace(generation_id="test-generation")
        )

    assert result["status"] == "OK"
    assert result["count"] == 1
    assert result["spot_rows_stored"] == 1680
    assert len(spot_repo.save_many.call_args.args[1]) == 480
    assert result["records"][0]["direction"] == "BULLISH"
    saved = trend_repo.save.call_args.args[1]
    assert saved["source"] == "market_participation_trend_v1"
    assert saved["external_context"]["status"] == "VERIFIED"
    assert saved["external_context"]["inputs"]["provider"] == "FRED"
    assert saved["components"]["external_context"] == 10
    assert trend_repo.save.call_args.kwargs["data_generation_id"] == "test-generation"
    assert result["macro"] == {
        "provider": "FRED",
        "status": "VERIFIED",
        "macro_score": 35.0,
        "series_count": 8,
        "data_timestamp": "2026-08-15",
        "advisory_only": True,
    }
    db.close.assert_called_once_with()


def test_derivative_context_excludes_stale_funding_and_open_interest():
    now = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)
    repository = Mock()
    repository.history_through.return_value = {
        "funding": [
            SimpleNamespace(
                rate=0.0001,
                funding_time=(now - timedelta(hours=13)).replace(tzinfo=None),
            )
        ],
        "open_interest": [
            SimpleNamespace(
                value=100.0,
                timestamp=(now - timedelta(minutes=25)).replace(tzinfo=None),
            ),
            SimpleNamespace(
                value=105.0,
                timestamp=(now - timedelta(minutes=20)).replace(tzinfo=None),
            ),
        ],
    }

    with patch(
        "app.jobs.market_participation_trend_job.DerivativeRepository",
        return_value=repository,
    ):
        result = _derivative_context(
            Mock(),
            "BTCUSDT",
            as_of_timestamp=now,
        )

    assert result["status"] == "DEGRADED"
    assert result["funding_rate"] is None
    assert result["open_interest_change_percent"] is None
    assert result["freshness"]["funding"]["is_stale"] is True
    assert result["freshness"]["open_interest"]["is_stale"] is True


def test_derivative_context_keeps_fresh_exchange_evidence():
    now = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)
    repository = Mock()
    repository.history_through.return_value = {
        "funding": [
            SimpleNamespace(
                rate=0.0001,
                funding_time=(now - timedelta(hours=8)).replace(tzinfo=None),
            )
        ],
        "open_interest": [
            SimpleNamespace(
                value=100.0,
                timestamp=(now - timedelta(minutes=10)).replace(tzinfo=None),
            ),
            SimpleNamespace(
                value=105.0,
                timestamp=(now - timedelta(minutes=5)).replace(tzinfo=None),
            ),
        ],
    }

    with patch(
        "app.jobs.market_participation_trend_job.DerivativeRepository",
        return_value=repository,
    ):
        result = _derivative_context(
            Mock(),
            "BTCUSDT",
            as_of_timestamp=now,
        )

    assert result["status"] == "READY"
    assert result["funding_rate"] == 0.0001
    assert result["open_interest_change_percent"] == 5.0


def test_liquidation_heatmap_ignores_events_outside_source_window():
    engine = create_engine("sqlite:///:memory:")
    Liquidation.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    now = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)
    try:
        db.add_all(
            [
                Liquidation(
                    venue="BINANCE",
                    exchange_event_id="old-event",
                    symbol="BTCUSDT",
                    side="BUY",
                    price=110.0,
                    quantity=1.0,
                    value_usd=10_000.0,
                    event_time=(now - timedelta(hours=5)).replace(tzinfo=None),
                ),
                Liquidation(
                    venue="BINANCE",
                    exchange_event_id="recent-event",
                    symbol="BTCUSDT",
                    side="SELL",
                    price=90.0,
                    quantity=1.0,
                    value_usd=1_000.0,
                    event_time=(now - timedelta(minutes=5)).replace(tzinfo=None),
                ),
            ]
        )
        db.commit()

        result = LiquidationHeatmapEngine().analyze(
            db,
            "BTCUSDT",
            100.0,
            as_of_timestamp=now,
        )

        assert result["source_event_count"] == 1
        assert result["above_value"] == 0
        assert result["below_value"] == 1_000.0
        assert result["bias"] == "HUNT_LONGS"
    finally:
        db.close()


def test_liquidation_context_rejects_stale_observed_event():
    now = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)
    event = SimpleNamespace(
        id=1,
        event_time=(now - timedelta(hours=1)).replace(tzinfo=None),
    )
    heatmap = SimpleNamespace(
        id=1,
        above_value=10_000.0,
        below_value=1_000.0,
        bias="HUNT_SHORTS",
        liquidity_above=110.0,
        liquidity_below=90.0,
        confidence=90.0,
        created_at=now.replace(tzinfo=None),
    )

    class Query:
        def __init__(self, value):
            self.value = value

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            return self.value

    class Db:
        def query(self, model):
            return Query(event if model is Liquidation else heatmap)

    result = _liquidation_context(
        Db(),
        "BTCUSDT",
        as_of_timestamp=now,
    )

    assert result["status"] == "STALE"
    assert result["data_quality"] == "STALE"
    assert result["freshness"]["is_stale"] is True


def test_liquidation_context_waits_for_heatmap_to_include_latest_event():
    now = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)
    event = SimpleNamespace(
        id=2,
        event_time=(now - timedelta(minutes=2)).replace(tzinfo=None),
    )
    heatmap = SimpleNamespace(
        id=1,
        above_value=10_000.0,
        below_value=1_000.0,
        bias="HUNT_SHORTS",
        liquidity_above=110.0,
        liquidity_below=90.0,
        confidence=90.0,
        created_at=(now - timedelta(minutes=3)).replace(tzinfo=None),
    )

    class Query:
        def __init__(self, value):
            self.value = value

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            return self.value

    class Db:
        def query(self, model):
            return Query(event if model is Liquidation else heatmap)

    result = _liquidation_context(
        Db(),
        "BTCUSDT",
        as_of_timestamp=now,
    )

    assert result["status"] == "PENDING"
    assert result["data_quality"] == "STALE"
    assert "awaiting heatmap refresh" in result["reason"]


def test_heatmap_repository_ignores_runtime_source_diagnostics():
    db = Mock()
    payload = {
        "symbol": "BTCUSDT",
        "current_price": 100.0,
        "liquidity_above": 110.0,
        "liquidity_below": 90.0,
        "above_value": 1_000.0,
        "below_value": 500.0,
        "target_price": 110.0,
        "bias": "HUNT_SHORTS",
        "confidence": 66.67,
        "source_window_start": datetime(2026, 8, 15, 12, 0),
        "source_window_end": datetime(2026, 8, 15, 16, 0),
        "source_event_count": 3,
    }

    with patch("app.repositories.heatmap_repository.commit_or_rollback"):
        HeatmapRepository().save(db, payload)

    saved = db.add.call_args.args[0]
    assert saved.symbol == "BTCUSDT"
    assert saved.bias == "HUNT_SHORTS"
    assert not hasattr(saved, "source_event_count")
