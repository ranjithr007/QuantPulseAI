import json
import subprocess
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql

from app.database.models.symbols import Symbol
from app.database.native_evidence_stage import MANIFEST_NAME
from app.database.native_evidence_stage import _copy_table_postgresql
from app.database.native_evidence_stage import build_bcp_query
from app.database.native_evidence_stage import export_table_bcp
from app.database.native_evidence_stage import iter_staged_rows
from app.database.native_evidence_stage import load_manifest
from app.database.native_evidence_stage import resilient_table_checksum
from app.database.native_evidence_stage import staged_file_evidence
from app.database.evidence_migration import table_checksum
from app.database.postgresql_baseline import POSTGRESQL_BASELINE_FINGERPRINT
from app.database.runtime import Base


def test_bcp_query_is_ordered_and_preserves_null_values():
    query = build_bcp_query(Symbol.__table__)

    assert "FROM dbo.[symbols] AS source" in query
    assert "INCLUDE_NULL_VALUES" in query
    assert "WITHOUT_ARRAY_WRAPPER" in query
    assert "ORDER BY source.[id]" in query


def test_bcp_export_retries_transient_connection_failure(tmp_path):
    path = tmp_path / "symbols.jsonl"
    failed = subprocess.CompletedProcess(
        args=["bcp"], returncode=1, stdout="", stderr="Login timeout"
    )

    calls = iter((failed, "success"))

    def run_bcp(*_args, **_kwargs):
        outcome = next(calls)
        if outcome is failed:
            return failed
        path.write_text(
            json.dumps(
                {
                    "id": 1,
                    "symbol": "BTCUSDT",
                    "base_asset": "BTC",
                    "quote_asset": "USDT",
                    "is_active": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            args=["bcp"], returncode=0, stdout="1 rows copied", stderr=""
        )

    with patch(
        "app.database.native_evidence_stage.subprocess.run",
        side_effect=run_bcp,
    ) as run:
        evidence = export_table_bcp(
            Symbol.__table__,
            path,
            server="test-server",
            database="test-database",
            retry_delay_seconds=0,
        )

    assert run.call_count == 2
    assert evidence["rows"] == 1


def test_staged_rows_validate_columns_and_preserve_types(tmp_path):
    path = tmp_path / "symbols.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": 7,
                "symbol": "DOGEUSDT",
                "base_asset": "DOGE",
                "quote_asset": "USDT",
                "is_active": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rows = list(iter_staged_rows(path, Symbol.__table__))
    evidence = staged_file_evidence(path, Symbol.__table__)

    assert rows == [
        {
            "id": 7,
            "symbol": "DOGEUSDT",
            "base_asset": "DOGE",
            "quote_asset": "USDT",
            "is_active": True,
        }
    ]
    assert evidence["rows"] == 1
    assert len(evidence["sha256"]) == 64


def test_postgresql_copy_streams_typed_rows(tmp_path):
    path = tmp_path / "symbols.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": 7,
                "symbol": "DOGEUSDT",
                "base_asset": "DOGE",
                "quote_asset": "USDT",
                "is_active": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class CopySink:
        def __init__(self):
            self.rows = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write_row(self, row):
            self.rows.append(row)

    sink = CopySink()
    cursor = SimpleNamespace(copy=lambda statement: sink)
    driver = SimpleNamespace(cursor=lambda: cursor)
    dialect = postgresql.dialect()
    connection = SimpleNamespace(
        dialect=dialect,
        connection=SimpleNamespace(driver_connection=driver),
    )

    copied = _copy_table_postgresql(connection, path, Symbol.__table__)

    assert copied == 1
    assert sink.rows == [(7, "DOGEUSDT", "DOGE", "USDT", True)]


def test_resilient_checksum_preserves_primary_key_order_across_batches():
    engine = create_engine("sqlite:///:memory:")
    Symbol.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            Symbol.__table__.insert(),
            [
                {"id": 11, "symbol": "ETHUSDT"},
                {"id": 3, "symbol": "BTCUSDT"},
                {"id": 19, "symbol": "DOGEUSDT"},
            ],
        )

    actual = resilient_table_checksum(engine, Symbol.__table__, batch_size=1)
    with engine.connect() as connection:
        expected = table_checksum(connection, Symbol.__table__, batch_size=1)

    assert actual == expected
    engine.dispose()


def test_staged_rows_reject_schema_drift(tmp_path):
    path = tmp_path / "symbols.jsonl"
    path.write_text('{"id":1,"symbol":"BTCUSDT"}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="Staged columns differ"):
        list(iter_staged_rows(path, Symbol.__table__))


def test_manifest_requires_all_tables_and_reviewed_fingerprint(tmp_path):
    records = [
        {"table": name, "file": f"{name}.jsonl", "rows": 0, "sha256": "0", "bytes": 0}
        for name in Base.metadata.tables
    ]
    manifest = {
        "format": "quantpulse-bcp-jsonl-v1",
        "created_at": datetime.utcnow().isoformat(),
        "schema_fingerprint": POSTGRESQL_BASELINE_FINGERPRINT,
        "table_count": len(records),
        "total_rows": 0,
        "tables": records,
    }
    (tmp_path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    assert load_manifest(tmp_path)["table_count"] == 44

    manifest["schema_fingerprint"] = "changed"
    (tmp_path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="fingerprint"):
        load_manifest(tmp_path)
