from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.database.models.whale_trades import WhaleTrade
from app.engines.whale_engine import WhaleEngine


def test_whale_engine_aggregates_recent_symbol_trades_in_database():
    engine = sa.create_engine("sqlite://")
    WhaleTrade.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    now = datetime.now()
    session.add_all(
        [
            WhaleTrade(
                venue="BINANCE",
                exchange_trade_id="buy-recent",
                symbol="BTCUSDT",
                side="BUY",
                price=1.0,
                quantity=1.0,
                value_usd=300.0,
                trade_time=now - timedelta(minutes=2),
            ),
            WhaleTrade(
                venue="BINANCE",
                exchange_trade_id="sell-recent",
                symbol="BTCUSDT",
                side="SELL",
                price=1.0,
                quantity=1.0,
                value_usd=100.0,
                trade_time=now - timedelta(minutes=3),
            ),
            WhaleTrade(
                venue="BINANCE",
                exchange_trade_id="buy-old",
                symbol="BTCUSDT",
                side="BUY",
                price=1.0,
                quantity=1.0,
                value_usd=10_000.0,
                trade_time=now - timedelta(minutes=16),
            ),
            WhaleTrade(
                venue="BINANCE",
                exchange_trade_id="other-symbol",
                symbol="ETHUSDT",
                side="SELL",
                price=1.0,
                quantity=1.0,
                value_usd=10_000.0,
                trade_time=now - timedelta(minutes=1),
            ),
        ]
    )
    session.commit()

    result = WhaleEngine().analyze(session, "BTCUSDT")

    assert result == {
        "symbol": "BTCUSDT",
        "buy_volume": 300.0,
        "sell_volume": 100.0,
        "net_flow": 200.0,
        "whale_score": 50.0,
        "bias": "ACCUMULATION",
        "confidence": 50.0,
    }
    session.close()
    engine.dispose()
