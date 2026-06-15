
from sqlalchemy import Column, Integer, String, Float, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class MLLabel(Base):

    __tablename__ = "ml_labels"

    id = Column(Integer, primary_key=True, index=True)

    symbol = Column(String(30), index=True)

    timestamp = Column(DateTime, index=True)

    current_price = Column(Float)

    future_price = Column(Float)

    future_return = Column(Float)

    #
    # AI target
    #
    # 1  = bullish
    # 0  = neutral
    # -1 = bearish
    #

    label = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)