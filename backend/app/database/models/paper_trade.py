from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.database.sqlserver import Base


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True)
    trade_plan_id = Column(Integer, index=True)
    risk_decision_id = Column(Integer, index=True)
    symbol = Column(String(30), index=True)
    side = Column(String(20))
    entry_price = Column(Float)
    stop_loss = Column(Float)
    target1 = Column(Float)
    target2 = Column(Float)
    position_size = Column(Float)
    risk_reward = Column(Float)
    risk_percent = Column(Float)
    confidence = Column(Float)
    status = Column(String(20), default="OPEN", index=True)
    exit_price = Column(Float, nullable=True)
    result = Column(String(20), nullable=True)
    pnl_percent = Column(Float, nullable=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
