
from sqlalchemy import Column, BigInteger, String, Float, DateTime

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class WhaleTrade(Base):

    __tablename__ = "whale_trades"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True)

    side = Column(String(10))

    price = Column(Float)

    quantity = Column(Float)

    value_usd = Column(Float)

    trade_time = Column(DateTime)

    created_at = Column(DateTime, server_default=func.now())