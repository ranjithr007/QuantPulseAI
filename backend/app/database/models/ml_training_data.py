
from sqlalchemy import Column, Integer, String, Float, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class MLTrainingData(Base):

    __tablename__ = "ml_training_data"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(30), index=True)

    timeframe = Column(String(10))

    # ==========================
    # FEATURE FACTORY
    # ==========================

    trend_score = Column(Float)

    momentum_score = Column(Float)

    volatility_score = Column(Float)

    # ==========================
    # REGIME ENGINE
    # ==========================

    regime = Column(String(50))

    regime_confidence = Column(Float)

    # ==========================
    # ORDER FLOW ENGINE
    # ==========================

    cvd = Column(Float)

    delta = Column(Float)

    buy_pressure = Column(Float)

    sell_pressure = Column(Float)

    # ==========================
    # SMART MONEY ENGINE
    # ==========================

    smc_bias = Column(String(20))

    smc_confidence = Column(Float)

    liquidity_sweep = Column(Integer)

    order_block = Column(Integer)

    fair_value_gap = Column(Integer)

    # ==========================
    # MARKET STRUCTURE
    # ==========================

    funding_rate = Column(Float)

    open_interest_change = Column(Float)

    liquidation_pressure = Column(Float)

    # ==========================
    # AI OUTPUT
    # ==========================

    signal = Column(String(20))
    entry_price = Column(Float)

    exit_price = Column(Float)

    confidence = Column(Float)

    profit_loss = Column(Float)
    future_price = Column(Float)

    future_return = Column(Float)

    label = Column(Integer)
    # 1 WIN
    # 0 LOSS
    evaluated = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)