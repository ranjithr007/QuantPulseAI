
from sqlalchemy import Column, BigInteger, String, Float, DateTime

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class WhaleSignal(Base):

    __tablename__ = "whale_signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True)

    buy_volume = Column(Float)

    sell_volume = Column(Float)

    net_flow = Column(Float)

    whale_score = Column(Float)

    bias = Column(String(50))

    confidence = Column(Float)

    created_at = Column(DateTime, server_default=func.now())