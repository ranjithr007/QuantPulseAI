from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.database.sqlserver import Base


class PaperWalletLedgerEntry(Base):
    __tablename__ = "paper_wallet_ledger"

    id = Column(Integer, primary_key=True)
    event_key = Column(String(160), nullable=False, unique=True)
    paper_trade_id = Column(Integer, nullable=False, index=True)
    symbol = Column(String(30), nullable=False, index=True)
    event_type = Column(String(40), nullable=False)
    delta_inr = Column(Float, nullable=False, default=0.0)
    position_notional_inr = Column(Float, nullable=True)
    margin_inr = Column(Float, nullable=True)
    position_fraction = Column(Float, nullable=True)
    pnl_percent = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
