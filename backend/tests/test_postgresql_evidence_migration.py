from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.database.evidence_migration import _canonical_value
from app.database.evidence_migration import copy_table
from app.database.evidence_migration import schema_inventory
from app.database.evidence_migration import table_checksum
from app.database.evidence_migration import validate_migration_endpoints
from app.database.models.symbols import Symbol


def _engine(backend):
    return SimpleNamespace(url=SimpleNamespace(get_backend_name=lambda: backend))


def test_migration_refuses_sqlite_fallback_source():
    with pytest.raises(RuntimeError, match="not canonical evidence"):
        validate_migration_endpoints(_engine("sqlite"), _engine("postgresql"))


def test_migration_refuses_non_postgresql_target():
    with pytest.raises(RuntimeError, match="target must be PostgreSQL"):
        validate_migration_endpoints(_engine("mssql"), _engine("sqlite"))


def test_inventory_reports_missing_tables_and_exact_symbol_schema():
    engine = create_engine("sqlite:///:memory:")
    Symbol.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            Symbol.__table__.insert(),
            [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}],
        )

    records = {record["table"]: record for record in schema_inventory(engine)}

    assert records["symbols"]["rows"] == 2
    assert records["symbols"]["schema_matches"] is True
    assert records["market_candles"]["available"] is False
    engine.dispose()


def test_table_copy_preserves_rows_and_checksum():
    source = create_engine("sqlite:///:memory:")
    target = create_engine("sqlite:///:memory:")
    Symbol.__table__.create(source)
    Symbol.__table__.create(target)
    with source.begin() as connection:
        connection.execute(
            Symbol.__table__.insert(),
            [{"id": 7, "symbol": "DOGEUSDT"}, {"id": 11, "symbol": "ETHUSDT"}],
        )

    with source.connect() as source_connection, target.begin() as target_connection:
        copied = copy_table(
            source_connection,
            target_connection,
            Symbol.__table__,
            batch_size=1,
        )

    with source.connect() as source_connection, target.connect() as target_connection:
        source_checksum = table_checksum(source_connection, Symbol.__table__)
        target_checksum = table_checksum(target_connection, Symbol.__table__)

    assert copied == 2
    assert source_checksum == target_checksum
    assert source_checksum["rows"] == 2
    source.dispose()
    target.dispose()


def test_checksum_canonicalization_covers_database_values():
    assert _canonical_value(Decimal("1.2300")) == "1.2300"
    assert _canonical_value(30.0) == "30.0"
    assert _canonical_value(6854.6505399999996) == "6854.65054"
    assert _canonical_value(9.571428571428727e-05) == "0.00009571428571428727"
    assert _canonical_value(datetime(2026, 8, 9, 12, 0, 1)) == (
        "2026-08-09T12:00:01"
    )
    assert _canonical_value(b"abc") == "616263"
