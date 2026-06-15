from sqlalchemy import Column
from sqlalchemy import Integer, String, Float, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class MarketRegime(Base):

    __tablename__ = "MarketRegimes"

    Id = Column(Integer, primary_key=True)

    Symbol = Column(String(20))

    Timeframe = Column(String(10))

    Regime = Column(String(50))

    Confidence = Column(Float)

    RecommendedStrategy = Column(String(100))

    Reason = Column(String)

    CreatedAt = Column(DateTime, default=datetime.utcnow)