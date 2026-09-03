from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, UniqueConstraint

from app.database.sqlserver import Base


class FeatureSnapshot(Base):
    __tablename__ = "feature_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "effective_timestamp",
            "feature_version",
            name="uq_feature_snapshots_identity",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), index=True, nullable=False)
    timeframe = Column(String(10), index=True, nullable=False)
    source_timestamp = Column(DateTime, nullable=False)
    effective_timestamp = Column(DateTime, index=True, nullable=False)
    feature_version = Column(String(40), nullable=False)
    quality_state = Column(String(20), nullable=False, default="UNKNOWN")
    data_generation_id = Column(String(100), index=True, nullable=True)
    snapshot_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "effective_timestamp",
            "decision_version",
            name="uq_decision_snapshots_identity",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), index=True, nullable=False)
    timeframe = Column(String(10), index=True, nullable=False)
    source_timestamp = Column(DateTime, nullable=False)
    effective_timestamp = Column(DateTime, index=True, nullable=False)
    feature_version = Column(String(40), nullable=False)
    decision_version = Column(String(40), nullable=False)
    strategy_id = Column(String(50), index=True, nullable=True)
    strategy_version = Column(String(50), index=True, nullable=True)
    quality_state = Column(String(20), nullable=False, default="UNKNOWN")
    decision = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=True)
    regime = Column(String(50), nullable=True)
    thesis_id = Column(String(80), nullable=True)
    data_generation_id = Column(String(100), index=True, nullable=True)
    snapshot_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


Index(
    "ix_decision_snapshots_participation_latest",
    DecisionSnapshot.decision_version,
    DecisionSnapshot.timeframe,
    DecisionSnapshot.symbol,
    DecisionSnapshot.effective_timestamp,
    DecisionSnapshot.id,
)
