"""Fingerprint-locked PostgreSQL baseline built from the reviewed ORM schema."""

import hashlib

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from sqlalchemy.schema import CreateTable

from app.database.runtime import Base
from app.database import models as _models  # noqa: F401


POSTGRESQL_BASELINE_FINGERPRINT = (
    "10d004c00b35c76c767b6a185a03c28da3242dd564c18937c4b94c1fc3a4ae3f"
)
POSTGRESQL_POST_BASELINE_TABLES = frozenset(
    {
        "walk_forward_jobs",
        "spot_market_candles",
        "orderbook_snapshots",
        "app_notifications",
    }
)


def _baseline_tables():
    return [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in POSTGRESQL_POST_BASELINE_TABLES
    ]


def compiled_postgresql_schema():
    dialect = postgresql.dialect()
    statements = []
    for table in _baseline_tables():
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip())
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip())
    return statements


def postgresql_schema_fingerprint():
    payload = "\n\n".join(compiled_postgresql_schema()).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_reviewed_postgresql_schema():
    actual = postgresql_schema_fingerprint()
    if actual != POSTGRESQL_BASELINE_FINGERPRINT:
        raise RuntimeError(
            "PostgreSQL ORM schema changed after baseline review: "
            f"expected {POSTGRESQL_BASELINE_FINGERPRINT}, got {actual}. "
            "Create a new PostgreSQL migration instead of mutating the baseline."
        )


def create_postgresql_baseline(bind):
    if bind.dialect.name != "postgresql":
        raise RuntimeError("The PostgreSQL baseline only supports PostgreSQL.")
    assert_reviewed_postgresql_schema()
    Base.metadata.create_all(bind=bind, tables=_baseline_tables(), checkfirst=False)


def drop_postgresql_baseline(bind):
    if bind.dialect.name != "postgresql":
        raise RuntimeError("The PostgreSQL baseline only supports PostgreSQL.")
    assert_reviewed_postgresql_schema()
    Base.metadata.drop_all(bind=bind, tables=_baseline_tables(), checkfirst=True)
