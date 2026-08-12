from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.database.sqlserver import Base
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE


class AutomationSetting(Base):
    __tablename__ = "automation_settings"

    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    locked = Column(Boolean, nullable=False, default=True)
    emergency_stop = Column(Boolean, nullable=False, default=False)
    allowed_symbols = Column(Text, nullable=False)
    max_risk_per_trade = Column(Float, nullable=False, default=1.0)
    daily_loss_limit = Column(Float, nullable=False, default=4.0)
    max_open_trades = Column(Integer, nullable=False, default=4)
    max_leverage = Column(Integer, nullable=False, default=5)
    max_position_size = Column(Float, nullable=False, default=25000)
    min_confidence = Column(
        Float,
        nullable=False,
        default=MIN_ENTRY_CONFIDENCE,
    )
    direction = Column(String(10), nullable=False, default="BOTH")
    execution_mode = Column(String(20), nullable=False, default="PAPER")
    version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AutomationSettingsAudit(Base):
    __tablename__ = "automation_settings_audit"

    id = Column(Integer, primary_key=True)
    setting_id = Column(Integer, nullable=False, index=True)
    action = Column(String(40), nullable=False)
    actor = Column(String(80), nullable=False, default="local_ui")
    changed_fields = Column(Text, nullable=False)
    previous_values = Column(Text, nullable=False)
    new_values = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
