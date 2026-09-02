from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors.binances.liquidation_collector import _parse_liquidation_message
from app.collectors.binances.orderbook_collector import OrderBookCollector
from app.database.models.funding_rates import FundingRate
from app.database.models.liquidations import Liquidation
from app.database.models.open_interest import OpenInterest
from app.database.models.orderbook_snapshots import OrderBookSnapshot
from app.database.models.spot_market_candles import SpotMarketCandle
from app.database.models.whale_trades import WhaleTrade
from app.repositories.derivative_repository import DerivativeRepository
from app.repositories.liquidation_repository import LiquidationRepository
from app.repositories.orderbook_snapshot_repository import OrderBookSnapshotRepository
from app.repositories.spot_market_repository import SpotMarketRepository
from app.repositories.whale_repository import WhaleRepository
from app.trading.market_participation_guard import evaluate_market_participation
from app.backtesting.trade_simulator import _reconstruct_market_participation_as_of


def _session(*tables):
    engine = create_engine("sqlite:///:memory:")
    for table in tables:
        table.__table__.create(engine)
    return sessionmaker(bind=engine)()


def test_funding_repository_charges_one_exchange_event_once():
    db = _session(FundingRate)
    event_time = datetime(2026, 8, 22, 8)
    repository = DerivativeRepository()

    first = repository.save_funding(
        db,
        {"symbol": "btcusdt", "rate": 0.0001, "time": event_time},
    )
    second = repository.save_funding(
        db,
        {"symbol": "BTCUSDT", "rate": 0.0002, "time": event_time},
    )

    assert first.id == second.id
    assert db.query(FundingRate).count() == 1
    assert db.query(FundingRate).one().rate == 0.0002


def test_open_interest_repository_keeps_first_sample_in_each_two_minute_bucket():
    # SQLite only auto-increments an exact INTEGER primary key; production uses
    # BIGINT. Create the equivalent test table explicitly so repository behavior
    # can be exercised without changing the production model.
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE open_interest (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol VARCHAR(20),
                value FLOAT,
                timestamp DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    db = sessionmaker(bind=engine)()
    repository = DerivativeRepository()
    start = datetime(2026, 8, 22, 8, 0, 10)

    first = repository.save_open_interest(
        db,
        {"symbol": "btcusdt", "value": 100, "time": start},
    )
    repeated = repository.save_open_interest(
        db,
        {
            "symbol": "BTCUSDT",
            "value": 101,
            "time": start + timedelta(minutes=1, seconds=40),
        },
    )
    next_bucket = repository.save_open_interest(
        db,
        {
            "symbol": "BTCUSDT",
            "value": 102,
            "time": start + timedelta(minutes=2),
        },
    )

    rows = db.query(OpenInterest).order_by(OpenInterest.timestamp.asc()).all()
    assert repeated is first
    assert next_bucket is not first
    assert len(rows) == 2
    assert rows[0].value == 100
    assert rows[0].timestamp == start
    assert rows[1].value == 102


def test_spot_repository_upserts_and_returns_point_in_time_history():
    db = _session(SpotMarketCandle)
    repository = SpotMarketRepository()
    start = datetime(2026, 8, 22, 8)
    rows = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "open_time": start + timedelta(hours=index),
            "close_time": start + timedelta(hours=index + 1),
            "open": 100 + index,
            "high": 102 + index,
            "low": 99 + index,
            "close": 101 + index,
            "base_volume": 10,
            "quote_volume": 1000,
            "trade_count": 25,
            "taker_buy_quote_volume": 600,
            "taker_sell_quote_volume": 400,
            "spot_delta_quote": 200,
            "is_final": True,
            "source": "BINANCE_SPOT_KLINE",
        }
        for index in range(2)
    ]

    repository.save_many(db, rows)
    updated = {**rows[0], "close": 111}
    repository.save_many(db, [updated])
    history = repository.history_through(
        db,
        "BTCUSDT",
        start + timedelta(hours=1, minutes=30),
        timeframes=("1h",),
    )

    assert db.query(SpotMarketCandle).count() == 2
    assert len(history["1h"]) == 1
    assert history["1h"][0]["close"] == 111
    assert history["1h"][0]["spot_delta_quote"] == 200


def test_whale_and_liquidation_exchange_events_are_deduplicated():
    db = _session(WhaleTrade, Liquidation)
    whale = {
        "venue": "BINANCE",
        "exchange_trade_id": "123",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "price": 100,
        "quantity": 2,
        "value_usd": 200,
        "trade_time": datetime(2026, 8, 22, 8),
    }
    repository = WhaleRepository()
    assert repository.save_many(db, [whale, whale]) == 1
    assert repository.save_many(db, [whale]) == 0

    message = (
        '{"E":1787385600000,"o":{"s":"BTCUSDT","S":"SELL",'
        '"p":"100","q":"2","T":1787385599000}}'
    )
    event = _parse_liquidation_message(message)
    liquidation_repository = LiquidationRepository()
    first = liquidation_repository.save(db, event)
    second = liquidation_repository.save(db, event)

    assert event["exchange_event_id"]
    assert first.id == second.id
    assert db.query(Liquidation).count() == 1


def test_historical_participation_freshness_uses_replay_cutoff():
    effective = datetime(2026, 8, 22, 8, tzinfo=timezone.utc)
    payload = {
        "status": "READY",
        "quality_state": "OK",
        "direction": "BULLISH",
        "score": 52,
        "confidence": 52,
        "effective_timestamp": effective,
    }

    result = evaluate_market_participation(
        payload,
        "LONG",
        as_of_timestamp=effective + timedelta(minutes=30),
    )

    assert result["allowed"] is True
    assert result["freshness"]["is_stale"] is False


def test_raw_spot_history_reconstructs_point_in_time_participation():
    cutoff = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)

    def history(symbol, timeframe):
        duration = {"1h": 1, "2h": 2, "4h": 4, "1d": 24}[timeframe]
        rows = []
        for index in range(30):
            close_time = cutoff - timedelta(hours=(29 - index) * duration)
            price = 100 + index
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time": close_time - timedelta(hours=duration),
                    "close_time": close_time,
                    "open": price,
                    "high": price + 2,
                    "low": price - 1,
                    "close": price + 1,
                    "quote_volume": 1000,
                    "spot_delta_quote": 300,
                    "is_final": True,
                }
            )
        return rows

    histories = {
        symbol: {
            timeframe: history(symbol, timeframe)
            for timeframe in ("1h", "2h", "4h", "1d")
        }
        for symbol in ("BTCUSDT", "ETHBTC")
    }
    result = _reconstruct_market_participation_as_of(
        "BTCUSDT",
        histories,
        cutoff,
        {
            "funding": {"rate": 0.0001},
            "open_interest": {"change_pct": 1.0},
        },
    )

    assert result["status"] == "READY"
    assert result["direction"] == "BULLISH"
    assert result["replay_source"] == "RECONSTRUCTED_RAW_SPOT_CANDLES"
    assert result["effective_timestamp"] == cutoff


def test_orderbook_snapshot_stores_compact_depth_evidence_once():
    event_time = datetime(2026, 8, 22, 8, tzinfo=timezone.utc)
    payload = OrderBookCollector.parse_snapshot(
        {
            "lastUpdateId": 99,
            "E": int(event_time.timestamp() * 1000),
            "bids": [["99.9", "10"], ["99.5", "20"]],
            "asks": [["100.1", "8"], ["100.5", "12"]],
        },
        "BTCUSDT",
    )

    assert payload["spread_percent"] > 0
    assert payload["bid_depth_1pct"] > payload["ask_depth_1pct"]
    assert payload["imbalance_percent"] > 0

    db = _session(OrderBookSnapshot)
    repository = OrderBookSnapshotRepository()
    first = repository.save(db, payload)
    second = repository.save(db, payload)

    assert first.id == second.id
    assert db.query(OrderBookSnapshot).count() == 1
