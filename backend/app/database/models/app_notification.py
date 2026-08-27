from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database.sqlserver import Base


class AppNotification(Base):
    """Persistent, deduplicated notification shown in the QuantPulseAI UI."""

    __tablename__ = "app_notifications"

    id = Column(Integer, primary_key=True)
    event_key = Column(String(180), nullable=False, unique=True, index=True)
    category = Column(String(30), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default="INFO", index=True)
    title = Column(String(160), nullable=False)
    message = Column(Text, nullable=False)
    symbol = Column(String(30), nullable=True, index=True)
    paper_trade_id = Column(Integer, nullable=True, index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    read_at = Column(DateTime, nullable=True, index=True)
