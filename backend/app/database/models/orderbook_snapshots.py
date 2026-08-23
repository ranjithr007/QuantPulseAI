from sqlalchemy import BigInteger
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import UniqueConstraint
from sqlalchemy.sql import func

from app.database.sqlserver import Base


class OrderBookSnapshot(Base):
    """Compact futures depth evidence suitable for minute-level replay."""

    __tablename__ = "orderbook_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "venue",
            "symbol",
            "last_update_id",
            name="uq_orderbook_snapshot_exchange_update",
        ),
    )

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    venue = Column(String(20), nullable=False, default="BINANCE")
    market_type = Column(String(20), nullable=False, default="USDT_FUTURES")
    symbol = Column(String(20), nullable=False, index=True)
    event_time = Column(DateTime, nullable=False)
    last_update_id = Column(String(40), nullable=False)
    best_bid = Column(Float, nullable=False)
    best_ask = Column(Float, nullable=False)
    mid_price = Column(Float, nullable=False)
    spread_percent = Column(Float, nullable=False)
    bid_depth_05pct = Column(Float, nullable=False)
    ask_depth_05pct = Column(Float, nullable=False)
    bid_depth_1pct = Column(Float, nullable=False)
    ask_depth_1pct = Column(Float, nullable=False)
    bid_depth_2pct = Column(Float, nullable=False)
    ask_depth_2pct = Column(Float, nullable=False)
    imbalance_percent = Column(Float, nullable=False)
    source = Column(String(40), nullable=False, default="BINANCE_FUTURES_DEPTH")
    created_at = Column(DateTime, server_default=func.now())


Index(
    "ix_orderbook_snapshots_lookup",
    OrderBookSnapshot.symbol,
    OrderBookSnapshot.event_time,
)
