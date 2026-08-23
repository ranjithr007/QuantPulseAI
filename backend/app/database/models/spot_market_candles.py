from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import UniqueConstraint
from sqlalchemy.sql import func

from app.database.sqlserver import Base


class SpotMarketCandle(Base):
    """Final Binance spot candle with the taker-volume fields used by spot CVD."""

    __tablename__ = "spot_market_candles"
    __table_args__ = (
        UniqueConstraint(
            "venue",
            "symbol",
            "timeframe",
            "open_time",
            name="uq_spot_market_candle_identity",
        ),
    )

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    venue = Column(String(20), nullable=False, default="BINANCE")
    market_type = Column(String(20), nullable=False, default="SPOT")
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    open_time = Column(DateTime, nullable=False)
    close_time = Column(DateTime, nullable=False)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    base_volume = Column(Float, nullable=False, default=0.0)
    quote_volume = Column(Float, nullable=False, default=0.0)
    trade_count = Column(Integer, nullable=False, default=0)
    taker_buy_quote_volume = Column(Float, nullable=False, default=0.0)
    taker_sell_quote_volume = Column(Float, nullable=False, default=0.0)
    spot_delta_quote = Column(Float, nullable=False, default=0.0)
    is_final = Column(Boolean, nullable=False, default=True)
    source = Column(String(40), nullable=False, default="BINANCE_SPOT_KLINE")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


Index(
    "ix_spot_market_candles_lookup",
    SpotMarketCandle.symbol,
    SpotMarketCandle.timeframe,
    SpotMarketCandle.close_time,
)
