from sqlalchemy import Column
from sqlalchemy import Integer, String, Float, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class TradeMemory(Base):

    __tablename__ = "trade_memory"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(30))

    direction = Column(String(20))

    entry = Column(Float)

    stop_loss = Column(Float)

    target = Column(Float)

    confidence = Column(Float)

    result = Column(String(20))

    pnl_percent = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)
