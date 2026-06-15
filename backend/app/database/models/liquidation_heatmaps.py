
from sqlalchemy import Column, BigInteger, String, Float, DateTime

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class LiquidationHeatmap(Base):

    __tablename__ = "liquidation_heatmaps"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True)

    current_price = Column(Float)

    liquidity_above = Column(Float)

    liquidity_below = Column(Float)

    above_value = Column(Float)

    below_value = Column(Float)

    target_price = Column(Float)

    bias = Column(String(50))

    confidence = Column(Float)

    created_at = Column(DateTime, server_default=func.now())