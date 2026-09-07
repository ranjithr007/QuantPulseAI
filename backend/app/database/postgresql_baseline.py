"""Fingerprint-locked PostgreSQL baseline built from the reviewed ORM schema."""

import hashlib
from functools import lru_cache

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from sqlalchemy.schema import CreateTable

from app.database.runtime import Base
from app.database import models as _models  # noqa: F401


POSTGRESQL_BASELINE_FINGERPRINT = (
    "5e41a87d3ff5dda26f0236fe5cdcc8955d317145a85c4aac309d3acbb66a1ca6"
)
POSTGRESQL_POST_BASELINE_TABLES = frozenset(
    {
        "walk_forward_jobs",
        "spot_market_candles",
        "orderbook_snapshots",
        "app_notifications",
        "strategy_learning_evaluations",
        "strategy_version_configs",
    }
)
POSTGRESQL_POST_BASELINE_COLUMNS = {
    "paper_trades": frozenset({"trailing_activation_r", "execution_evidence_json", "exit_evidence_json"}),
    "strategy_shadow_trades": frozenset({"trailing_activation_r", "execution_evidence_json", "exit_evidence_json"}),
}
POSTGRESQL_POST_BASELINE_INDEXES = frozenset({"ix_paper_trades_closed_history"})


@lru_cache(maxsize=1)
def _reviewed_baseline_metadata():
    """Project only explicitly migrated additions out of an isolated copy.

    The original fingerprint remains locked. Runtime ORM tables are never
    mutated, and any unrelated schema change still fails baseline review.
    Forward migrations add these nullable columns/index to a new installation.
    """
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    # Preserve exact original DDL/constraint order for unaffected tables.
    for table_name in POSTGRESQL_POST_BASELINE_COLUMNS:
        Base.metadata.tables[table_name].to_metadata(metadata)
    for table_name, column_names in POSTGRESQL_POST_BASELINE_COLUMNS.items():
        table = metadata.tables[table_name]
        for name in column_names:
            if name in table.c:
                # SQLAlchemy exposes no public drop-column operation for an
                # in-memory Table. This edits only the isolated frozen copy.
                table._columns.remove(table.c[name])
    for table in metadata.tables.values():
        for index in tuple(table.indexes):
            if index.name in POSTGRESQL_POST_BASELINE_INDEXES:
                table.indexes.remove(index)
    return metadata


def _baseline_tables():
    projected = _reviewed_baseline_metadata().tables
    return [
        projected[table.name] if table.name in projected else table
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
