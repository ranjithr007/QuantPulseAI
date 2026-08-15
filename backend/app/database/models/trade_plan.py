
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

    mode = Column(String(20), nullable=True)

    entry_timeframe = Column(String(10), nullable=True)

    timeframe_stack = Column(String(40), nullable=True)

    regime = Column(String(50), nullable=True)

    thesis_id = Column(Integer, nullable=True, index=True)

    data_generation_id = Column(String(100), index=True, nullable=True)

    exit_policy = Column(String(50), nullable=True)

    target1_fraction = Column(Float, nullable=True)

    max_hold_hours = Column(Integer, nullable=True)

    status = Column(String(20), default="OPEN")

    exit_price = Column(Float, nullable=True)

    result = Column(String(20), nullable=True)

    pnl_percent = Column(Float, nullable=True)

    closed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
