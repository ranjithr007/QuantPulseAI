from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import DateTime

from datetime import datetime

from app.database.sqlserver import Base


class MarketOrderFlow(Base):

    __tablename__ = "MarketOrderFlow"

    Id = Column(Integer, primary_key=True)

    Symbol = Column(String(20))

    Timeframe = Column(String(10))

    BuyVolume = Column(Float)

    SellVolume = Column(Float)

    Delta = Column(Float)

    CVD = Column(Float)

    BuyerStrength = Column(Float)

    SellerStrength = Column(Float)

    Absorption = Column(String(50))

    Exhaustion = Column(String(50))

    FlowSignal = Column(String(50))

    Confidence = Column(Float)

    CreatedAt = Column(DateTime, default=datetime.now)