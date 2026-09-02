from types import SimpleNamespace

from sqlalchemy import create_engine

from app.observability.database_storage import build_database_storage_report


def _settings():
    return SimpleNamespace(
        pipeline_retention_enabled=True,
        pipeline_retention_days=30,
        pipeline_retention_batch_size=2500,
    )


def test_non_postgresql_storage_report_is_explicitly_unavailable():
    engine = create_engine("sqlite://")
    try:
        report = build_database_storage_report(engine, _settings())
    finally:
        engine.dispose()

    assert report["status"] == "UNAVAILABLE"
    assert report["backend"] == "sqlite"
    assert report["retention"]["protected_evidence_deleted"] is False


def test_postgresql_storage_report_classifies_evidence_and_retention_tables():
    rows = [
        {
            "table_name": "decision_snapshots",
            "total_bytes": 4096,
            "table_bytes": 3072,
            "index_bytes": 1024,
            "estimated_rows": 90,
            "dead_rows": 10,
        },
        {
            "table_name": "pipeline_runs",
            "total_bytes": 2048,
            "table_bytes": 1024,
            "index_bytes": 1024,
            "estimated_rows": 50,
            "dead_rows": 0,
        },
    ]
    engine = _FakeEngine(8192, rows)

    report = build_database_storage_report(engine, _settings(), table_limit=2)

    assert report["status"] == "AVAILABLE"
    assert report["database_size"] == "8.00 KB"
    assert report["tables"][0]["classification"] == "PROTECTED_BACKTEST_EVIDENCE"
    assert report["tables"][0]["dead_row_percent"] == 10.0
    assert report["tables"][1]["classification"] == "OPERATIONAL_RETENTION"
    assert engine.connection.parameters == {"table_limit": 2}


class _FakeEngine:
    def __init__(self, database_bytes, rows):
        self.url = SimpleNamespace(get_backend_name=lambda: "postgresql")
        self.connection = _FakeConnection(database_bytes, rows)

    def connect(self):
        return self.connection


class _FakeConnection:
    def __init__(self, database_bytes, rows):
        self.database_bytes = database_bytes
        self.rows = rows
        self.calls = 0
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _statement, parameters=None):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(scalar=lambda: self.database_bytes)
        self.parameters = parameters
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(all=lambda: self.rows)
        )
