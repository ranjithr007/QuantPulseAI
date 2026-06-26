from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Float, Integer, String, Text

from app.database.sqlserver import Base


class TradeThesis(Base):
    __tablename__ = "trade_theses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thesis_key = Column(String(100), nullable=False, unique=True, index=True)
    symbol = Column(String(30), nullable=False, index=True)
    side = Column(String(20), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    lifecycle_state = Column(String(20), nullable=False, default="DRAFT", index=True)
    lifecycle_reason = Column(String(1000), nullable=True)
    source_signal = Column(String(20), nullable=True)
    confidence = Column(Float, nullable=True)
    mode = Column(String(20), nullable=True)
    entry_timeframe = Column(String(10), nullable=True)
    timeframe_stack = Column(String(40), nullable=True)
    regime = Column(String(50), nullable=True)
    trade_plan_id = Column(Integer, nullable=True, index=True)
    risk_decision_id = Column(Integer, nullable=True, index=True)
    paper_trade_id = Column(Integer, nullable=True, index=True)
    assumptions_json = Column(Text, nullable=False)
    invalidation_json = Column(Text, nullable=False)
    targets_json = Column(Text, nullable=False)
    scenario_json = Column(Text, nullable=True)
    contradiction_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    invalidated_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
