
from sqlalchemy import Column, BigInteger, String, Float, Boolean, DateTime

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class SignalQuality(Base):

    __tablename__ = "signal_quality"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True)

    signal = Column(String(20))

    quality_grade = Column(String(5))

    confidence = Column(Float)

    risk_score = Column(Float)

    trade_allowed = Column(Boolean)

    reason = Column(String(1000))

    created_at = Column(DateTime, server_default=func.now())