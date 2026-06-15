
from sqlalchemy import Column, BigInteger, String, Float, DateTime

from sqlalchemy import Index
from app.database.sqlserver import Base


class MarketCandle(Base):

    __tablename__ = "market_candles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True, nullable=False)

    timeframe = Column(String(10), index=True)

    open_price = Column(Float)

    high_price = Column(Float)

    low_price = Column(Float)

    close_price = Column(Float)

    volume = Column(Float)

    candle_time = Column(DateTime, index=True)


Index(
    "idx_symbol_timeframe_time",
    MarketCandle.symbol,
    MarketCandle.timeframe,
    MarketCandle.candle_time,
)