from sqlalchemy import Column
from sqlalchemy import Integer, String, Float, DateTime
from datetime import datetime

from app.database.sqlserver import Base


class MarketFeature(Base):

    __tablename__ = "MarketFeatures"

    Id = Column(Integer, primary_key=True, index=True)

    Symbol = Column(String(20))

    Timeframe = Column(String(10))

    TrendScore = Column(Float)

    MomentumScore = Column(Float)

    ATR = Column(Float)

    VolatilityScore = Column(Float)

    LiquidityScore = Column(Float)

    FinalScore = Column(Float)

    Trend = Column(String(50))

    Signal = Column(String(50))

    CreatedAt = Column(DateTime, default=datetime.utcnow)