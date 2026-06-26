from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, BigInteger, String, Text

from app.database.sqlserver import Base


class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"
    __table_args__ = (
        Index(
            "ix_data_quality_events_symbol_timeframe_created_at",
            "symbol",
            "timeframe",
            "created_at",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    source = Column(String(40), nullable=False, index=True)
    category = Column(String(40), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default="warning")
    status = Column(String(20), nullable=False, default="WARN")
    blocked = Column(Boolean, nullable=False, default=False)
    reason = Column(String(1000), nullable=False)
    details_json = Column(Text, nullable=False)
    observed_at = Column(DateTime, nullable=False, index=True)
    effective_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
