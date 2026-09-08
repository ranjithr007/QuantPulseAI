from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.database.models.liquidations import Liquidation
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.spot_market_candles import SpotMarketCandle
from app.engines.liquidation_heatmap_engine import LiquidationHeatmapEngine
from app.jobs.market_participation_trend_job import _derivative_context
from app.jobs.market_participation_trend_job import _liquidation_context
from app.jobs.market_participation_trend_job import run_market_participation_trend_job
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.market_participation_repository import MarketParticipationRepository


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
        return_value={"data_quality": "OBSERVED", "direction_method": "ORDER_SIDE_V1", "imbalance_score": 100, "bias": "SHORT_LIQUIDATIONS"},
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


def test_recollection_records_fresh_observation_without_retimestamping_closed_candles():
    engine = create_engine("sqlite:///:memory:")
    SpotMarketCandle.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    source_close = datetime(2026, 8, 15, 16, 0)
    first_collection = source_close.replace(tzinfo=timezone.utc) + timedelta(minutes=2)
    second_collection = first_collection + timedelta(minutes=5)
    collector = Mock()

    def final_candles(symbol, timeframe, limit):
        period = timedelta(hours={"1h": 1, "2h": 2, "4h": 4, "1d": 24}[timeframe])
        rows = _bullish_bars(timeframe)
        for index, row in enumerate(rows):
            row.update(symbol=symbol, open_time=source_close - period * (len(rows) - index),
                       close_time=source_close - period * (len(rows) - index - 1))
        return rows

    collector.get_klines.side_effect = final_candles
    symbol_repository = Mock()
    symbol_repository.get_active_symbols.return_value = [SimpleNamespace(symbol="BTCUSDT")]
    fred_collector = Mock()
    fred_collector.collect.return_value = {"status": "UNAVAILABLE"}
    derivative_context = Mock(return_value={})
    liquidation_context = Mock(return_value={})
    collection_times = iter([first_collection, second_collection])

    def after_collection(zone):
        # The observation clock is sampled only after all external collection
        # and the per-symbol derivative/liquidation context have completed.
        assert zone is timezone.utc
        assert collector.get_klines.call_count == 8 * derivative_context.call_count
        assert liquidation_context.call_count == derivative_context.call_count
        assert fred_collector.collect.call_count == derivative_context.call_count
        return next(collection_times)

    try:
        with patch("app.jobs.market_participation_trend_job.SessionLocal", session_factory), patch(
            "app.jobs.market_participation_trend_job.SpotMarketCollector", return_value=collector,
        ), patch(
            "app.jobs.market_participation_trend_job.SymbolRepository", return_value=symbol_repository,
        ), patch(
            "app.jobs.market_participation_trend_job.FredMacroCollector", return_value=fred_collector,
        ), patch(
            "app.jobs.market_participation_trend_job._derivative_context", derivative_context,
        ), patch(
            "app.jobs.market_participation_trend_job._liquidation_context", liquidation_context,
        ), patch("app.jobs.market_participation_trend_job.datetime") as observation_clock:
            observation_clock.now.side_effect = after_collection
            first_run = run_market_participation_trend_job(context=SimpleNamespace(generation_id="scan-one"))
            assert first_run["status"] == "OK"
            with session_factory() as db:
                first = MarketParticipationRepository().latest(db, "BTCUSDT")

            second_run = run_market_participation_trend_job(context=SimpleNamespace(generation_id="scan-two"))
            assert second_run["status"] == "OK"
            with session_factory() as db:
                repository = MarketParticipationRepository()
                second = repository.latest(db, "BTCUSDT")
                assert db.query(DecisionSnapshot).count() == 1
                assert first["id"] == second["id"]
                assert first["created_at"] == second["created_at"]
                assert first["effective_timestamp"] == second["effective_timestamp"] == source_close
                assert first["source_timestamp"] == second["source_timestamp"]
                assert first["spot"] == second["spot"]
                assert first["score"] == second["score"]
                assert first["collected_at"] == first_collection.isoformat()
                assert second["collected_at"] == second_collection.isoformat()
                assert first["data_generation_id"] == "scan-one"
                assert second["data_generation_id"] == "scan-two"
                # All persisted read routes retain the recorded observation;
                # none fabricate a fresh clock value while serving a cache.
                assert repository.latest(db, "BTCUSDT")["collected_at"] == second["collected_at"]
                assert repository.latest_for_symbols(db, ["BTCUSDT"])["BTCUSDT"]["collected_at"] == second["collected_at"]
                assert repository.history_through(db, "BTCUSDT")[-1]["collected_at"] == second["collected_at"]
            assert observation_clock.now.call_count == 2
    finally:
        engine.dispose()


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
        assert result["bias"] == "LONG_LIQUIDATIONS"
    finally:
        db.close()


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
        "direction_method": "ORDER_SIDE_V1", "imbalance_score": 100, "bias": "SHORT_LIQUIDATIONS",
        "confidence": 66.67,
        "source_window_start": datetime(2026, 8, 15, 12, 0),
        "source_window_end": datetime(2026, 8, 15, 16, 0),
        "source_event_count": 3,
    }

    with patch("app.repositories.heatmap_repository.commit_or_rollback"):
        HeatmapRepository().save(db, payload)

    saved = db.add.call_args.args[0]
    assert saved.symbol == "BTCUSDT"
    assert saved.bias == "SHORT_LIQUIDATIONS"
    assert not hasattr(saved, "source_event_count")
