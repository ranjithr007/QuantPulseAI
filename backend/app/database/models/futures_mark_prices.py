from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import String
from sqlalchemy import UniqueConstraint
from sqlalchemy.sql import func

from app.database.sqlserver import Base


class FuturesMarkPrice(Base):
    __tablename__ = "futures_mark_prices"
    __table_args__ = (
        UniqueConstraint(
            "venue",
            "market_type",
            "symbol",
            "timeframe",
            "open_time",
            name="uq_futures_mark_price_identity",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    venue = Column(String(20), nullable=False, default="BINANCE")
    market_type = Column(String(20), nullable=False, default="USDT_FUTURES")
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    open_time = Column(DateTime, nullable=False)
    close_time = Column(DateTime, nullable=False)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    is_final = Column(Boolean, nullable=False, default=True)
    source = Column(String(40), nullable=False, default="BINANCE_MARK_PRICE_KLINES")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
