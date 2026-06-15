
from sqlalchemy import Column, BigInteger, String, Float, Boolean, DateTime

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class BacktestResult(Base):

    __tablename__ = "backtest_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True)

    signal = Column(String(20))

    entry_price = Column(Float)

    exit_price = Column(Float)

    pnl_percent = Column(Float)

    is_win = Column(Boolean)

    confidence = Column(Float)

    created_at = Column(DateTime, server_default=func.now())