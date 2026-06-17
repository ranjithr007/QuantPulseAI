from sqlalchemy import Column, Integer, String, Float, DateTime

from datetime import datetime

from app.database.sqlserver import Base


class OrderFlowSignal(Base):

    __tablename__ = "order_flow_signals"

    id = Column(Integer, primary_key=True)

    symbol = Column(String(30), index=True)

    # -------------------
    # Volume Delta
    # -------------------

    buy_volume = Column(Float)

    sell_volume = Column(Float)

    delta = Column(Float)

    cumulative_delta = Column(Float)

    # -------------------
    # Pressure
    # -------------------

    buy_pressure = Column(Float)

    sell_pressure = Column(Float)

    aggressive_side = Column(String(20))

    # -------------------
    # Whale Activity
    # -------------------

    whale_buy_count = Column(Integer)

    whale_sell_count = Column(Integer)

    whale_buy_volume = Column(Float)

    whale_sell_volume = Column(Float)

    largest_trade_value = Column(Float)

    # -------------------
    # Absorption Detection
    # -------------------

    absorption_type = Column(String(30))

    absorption_strength = Column(Float)

    # examples:
    #
    # BUY_ABSORPTION
    # SELL_ABSORPTION
    # NONE

    # -------------------
    # Exhaustion Detection
    # -------------------

    exhaustion_type = Column(String(30))

    exhaustion_strength = Column(Float)

    # examples:
    #
    # BUYER_EXHAUSTION
    # SELLER_EXHAUSTION

    # -------------------
    # Price Reaction
    # -------------------

    start_price = Column(Float)

    end_price = Column(Float)

    price_change_pct = Column(Float)

    # -------------------
    # AI Score
    # -------------------

    orderflow_score = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)
