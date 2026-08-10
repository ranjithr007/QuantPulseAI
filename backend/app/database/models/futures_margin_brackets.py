from sqlalchemy import BigInteger
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import UniqueConstraint
from sqlalchemy.sql import func

from app.database.sqlserver import Base


class FuturesMarginBracket(Base):
    __tablename__ = "futures_margin_brackets"
    __table_args__ = (
        UniqueConstraint(
            "venue",
            "symbol",
            "snapshot_version",
            "bracket_number",
            name="uq_futures_margin_bracket_snapshot",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    venue = Column(String(20), nullable=False, default="BINANCE")
    symbol = Column(String(20), nullable=False, index=True)
    snapshot_version = Column(String(64), nullable=False)
    effective_at = Column(DateTime, nullable=False)
    bracket_number = Column(Integer, nullable=False)
    notional_floor = Column(Float, nullable=False)
    notional_cap = Column(Float, nullable=False)
    initial_leverage = Column(Float)
    maintenance_margin_rate = Column(Float, nullable=False)
    maintenance_amount = Column(Float, nullable=False, default=0)
    source = Column(String(40), nullable=False, default="BINANCE_LEVERAGE_BRACKET")
    created_at = Column(DateTime, server_default=func.now())
