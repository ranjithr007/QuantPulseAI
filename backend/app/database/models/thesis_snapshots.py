from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.database.sqlserver import Base


class ThesisSnapshot(Base):
    __tablename__ = "thesis_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "thesis_id",
            "effective_timestamp",
            "snapshot_version",
            name="uq_thesis_snapshots_identity",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    thesis_id = Column(Integer, nullable=False, index=True)
    thesis_key = Column(String(100), nullable=False, index=True)
    symbol = Column(String(30), nullable=False, index=True)
    side = Column(String(20), nullable=False, index=True)
    lifecycle_state = Column(String(20), nullable=False, index=True)
    source_timestamp = Column(DateTime, nullable=False)
    effective_timestamp = Column(DateTime, index=True, nullable=False)
    snapshot_version = Column(String(40), nullable=False)
    snapshot_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
