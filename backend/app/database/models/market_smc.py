
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class MarketSMCSignal(Base):

    __tablename__ = "market_smc_signals"

    id = Column(Integer, primary_key=True, index=True)

    symbol = Column(String(20), index=True)

    timeframe = Column(String(10))

    # Structure

    bos_detected = Column(Boolean)
    bos_type = Column(String(30))

    choch_detected = Column(Boolean)
    choch_type = Column(String(30))

    structure = Column(String(30))

    # Order block

    order_block_type = Column(String(20))

    order_block_price = Column(Float)

    # Fair value gap

    fvg_detected = Column(Boolean)

    fvg_price = Column(Float)

    # Liquidity

    liquidity_sweep = Column(Boolean)

    sweep_price = Column(Float)

    # Final SMC decision

    smc_bias = Column(String(20))

    confidence = Column(Float)

    data_generation_id = Column(String(100), index=True, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
