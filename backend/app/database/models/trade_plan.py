
from sqlalchemy import Column, Integer, String, Float, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class TradePlan(Base):

    __tablename__ = "trade_plans"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(30))

    side = Column(String(20))

    entry_price = Column(Float)

    stop_loss = Column(Float)

    target1 = Column(Float)

    target2 = Column(Float)

    target3 = Column(Float)

    risk_reward = Column(Float)

    confidence = Column(Float)

    status = Column(String(20), default="OPEN")

    exit_price = Column(Float, nullable=True)

    result = Column(String(20), nullable=True)

    pnl_percent = Column(Float, nullable=True)

    closed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.now)