
from sqlalchemy import Column, Integer, String, Float, DateTime

from datetime import datetime
from app.database.sqlserver import Base


class RiskDecision(Base):

    __tablename__ = "risk_decisions"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(30), index=True)

    signal = Column(String(20))

    decision = Column(String(40))

    entry_price = Column(Float)

    stop_loss = Column(Float)

    target1 = Column(Float)

    target2 = Column(Float)

    risk_reward = Column(Float)

    position_size = Column(Float)

    risk_percent = Column(Float)

    confidence = Column(Float)

    thesis_id = Column(Integer, nullable=True, index=True)

    data_generation_id = Column(String(100), index=True, nullable=True)

    strategy_id = Column(String(50), index=True, nullable=True)

    strategy_version = Column(String(50), index=True, nullable=True)

    strategy_decision_snapshot_id = Column(Integer, index=True, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
