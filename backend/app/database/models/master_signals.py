
from sqlalchemy import Column, Integer, String, Float, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class MasterSignal(Base):

    __tablename__ = "master_signals"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(30), index=True)

    signal = Column(String(20))

    confidence = Column(Float)

    # Engine scores

    long_score = Column(Float)

    short_score = Column(Float)

    orderflow_score = Column(Float)

    risk = Column(String(20))

    entry_price = Column(Float)

    target_price = Column(Float)

    reasons = Column(String(1000))

    created_at = Column(DateTime, default=datetime.utcnow)
