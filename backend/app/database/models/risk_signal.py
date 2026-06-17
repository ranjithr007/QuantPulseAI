
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class RiskSignal(Base):

    __tablename__ = "risk_signals"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(30))

    direction = Column(String(20))

    entry_price = Column(Float)

    stop_loss = Column(Float)

    target_price = Column(Float)

    risk_reward = Column(Float)

    position_size = Column(Float)

    max_loss = Column(Float)

    trade_allowed = Column(Boolean)

    reason = Column(String(500))

    created_at = Column(DateTime, default=datetime.utcnow)
