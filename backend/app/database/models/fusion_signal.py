from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime

from app.database.sqlserver import Base


class FusionSignal(Base):

    __tablename__ = "fusion_signals"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(30), index=True)

    decision = Column(String(30))

    confidence = Column(Float)

    timeframe = Column(String(5))

    ml_score = Column(Float)

    regime_score = Column(Float)

    orderflow_score = Column(Float)

    smc_score = Column(Float)

    liquidation_score = Column(Float)

    whale_score = Column(Float)

    data_generation_id = Column(String(100), index=True, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
