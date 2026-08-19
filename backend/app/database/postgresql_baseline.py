"""Fingerprint-locked PostgreSQL baseline built from the reviewed ORM schema."""

import hashlib

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from sqlalchemy.schema import CreateTable

from app.database.runtime import Base
from app.database import models as _models  # noqa: F401


POSTGRESQL_BASELINE_FINGERPRINT = (
    "5bbaaa6467db1528872c87b124f712e9cc45b4154659207a33417a5f218a152e"
)
POSTGRESQL_POST_BASELINE_TABLES = frozenset({"walk_forward_jobs"})


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
