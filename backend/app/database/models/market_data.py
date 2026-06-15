from sqlalchemy import Column, Integer, String, Float, DateTime
from app.database.sqlserver import Base


class MarketData(Base):

    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, index=True)

    symbol = Column(String(30), index=True)

    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)

    volume = Column(Float)

    timestamp = Column(DateTime, index=True)