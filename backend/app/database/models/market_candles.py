
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy import false
from sqlalchemy import text

from sqlalchemy import Index
from app.database.sqlserver import Base


class MarketCandle(Base):

    __tablename__ = "market_candles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True, nullable=False)

    timeframe = Column(String(10), index=True)

    venue = Column(String(20), nullable=False, server_default="UNKNOWN")

    market_type = Column(String(20), nullable=False, server_default="FUTURES")

    open_price = Column(Float)

    high_price = Column(Float)

    low_price = Column(Float)

    close_price = Column(Float)

    volume = Column(Float)

    candle_time = Column(DateTime, index=True)

    open_time = Column(DateTime, nullable=False)

    close_time = Column(DateTime, nullable=False)

    is_final = Column(Boolean, nullable=False, default=False, server_default=false())

    source = Column(String(40), nullable=False, server_default="LEGACY_UNKNOWN")

    ingested_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    revision = Column(Integer, nullable=False, default=0, server_default=text("0"))

    quality_state = Column(
        String(30),
        nullable=False,
        server_default="LEGACY_UNVERIFIED",
    )


Index(
    "idx_symbol_timeframe_time",
    MarketCandle.symbol,
    MarketCandle.timeframe,
    MarketCandle.candle_time,
)

Index(
    "uq_market_candles_canonical_identity",
    MarketCandle.venue,
    MarketCandle.market_type,
    MarketCandle.symbol,
    MarketCandle.timeframe,
    MarketCandle.open_time,
    unique=True,
)

Index(
    "idx_market_candles_symbol_timeframe_open",
    MarketCandle.symbol,
    MarketCandle.timeframe,
    MarketCandle.open_time,
)
