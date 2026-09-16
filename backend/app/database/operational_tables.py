from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, Text


# Operational liveness is intentionally separate from the immutable evidence
# ORM metadata used by native evidence staging and its fingerprint.
operational_metadata = MetaData()

fast_exit_heartbeats = Table(
    "fast_exit_heartbeats",
    operational_metadata,
    Column("id", Integer, primary_key=True),
    Column("last_attempt_at", DateTime, nullable=True),
    Column("last_success_at", DateTime, nullable=True),
    Column("last_status", String(20), nullable=False),
    Column("last_duration_seconds", Float, nullable=True),
    Column("last_error", Text, nullable=True),
    Column("consecutive_failures", Integer, nullable=False),
    Column("price_stream_json", Text, nullable=True),
)

