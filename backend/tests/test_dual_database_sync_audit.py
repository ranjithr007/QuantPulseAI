"""The dual-database preflight reports differences without changing either DB."""

import importlib.util
from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_dual_database_sync.py"
spec = importlib.util.spec_from_file_location("audit_dual_database_sync", SCRIPT)
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


def test_audit_detects_local_only_railway_only_and_conflicting_rows():
    local = create_engine("sqlite://")
    railway = create_engine("sqlite://")
    metadata = MetaData()
    table = Table("records", metadata, Column("id", Integer, primary_key=True), Column("value", String))
    metadata.create_all(local)
    metadata.create_all(railway)
    with local.begin() as connection:
        connection.execute(insert(table), [
            {"id": 1, "value": "same"},
            {"id": 2, "value": "local"},
            {"id": 3, "value": "local only"},
        ])
    with railway.begin() as connection:
        connection.execute(insert(table), [
            {"id": 1, "value": "same"},
            {"id": 2, "value": "railway"},
            {"id": 4, "value": "railway only"},
        ])

    report = audit_module.audit(local, railway, scan_conflicts=True)

    assert report["compatible_tables"] == 1
    assert report["tables"][0]["row_comparison"] == {
        "local_only": 1,
        "railway_only": 1,
        "matching": 1,
        "conflicting": 1,
        "conflict_key_samples": [2],
    }
    with local.connect() as connection:
        assert connection.execute(select(table).order_by(table.c.id)).all()[1].value == "local"
    with railway.connect() as connection:
        assert connection.execute(select(table).order_by(table.c.id)).all()[1].value == "railway"
