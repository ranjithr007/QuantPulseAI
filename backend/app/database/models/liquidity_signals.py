
from sqlalchemy import Column, BigInteger, String, Float, DateTime

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class LiquiditySignal(Base):

    __tablename__ = "liquidity_signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True)

    signal = Column(String(50))

    long_squeeze_probability = Column(Float)

    short_squeeze_probability = Column(Float)

    confidence = Column(Float)

    created_at = Column(DateTime, server_default=func.now())