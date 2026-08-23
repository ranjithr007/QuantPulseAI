
from sqlalchemy import Column, BigInteger, String, Float, DateTime, Index, Integer

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class WhaleTrade(Base):

    __tablename__ = "whale_trades"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    venue = Column(String(20), nullable=False, default="BINANCE")

    exchange_trade_id = Column(String(40), nullable=True)

    symbol = Column(String(20), index=True)

    side = Column(String(10))

    price = Column(Float)

    quantity = Column(Float)

    value_usd = Column(Float)

    trade_time = Column(DateTime)

    created_at = Column(DateTime, server_default=func.now())


Index(
    "uq_whale_trades_exchange_event",
    WhaleTrade.venue,
    WhaleTrade.symbol,
    WhaleTrade.exchange_trade_id,
    unique=True,
)
