from datetime import datetime

from app.contracts.health import DependencyHealthResponse
from app.contracts.health import HealthResponse
from app.contracts.health import PipelineHealthResponse


def test_health_contracts_accept_success_and_fallback_shapes():
    health = HealthResponse(
        system="QuantPulse AI",
        version="3.0",
        environment="development",
        status="running",
        scheduler_enabled=True,
        process_role="all",
        admin_auth_required=False,
    )
    dependencies = DependencyHealthResponse(
        database_configured=True,
        database_url_scheme="mssql+pyodbc",
        active_database_scheme="mssql",
        using_sqlite_fallback=False,
        evidence_storage="SQL_SERVER",
    )
    postgres_dependencies = DependencyHealthResponse(
        database_configured=True,
        database_url_scheme="postgresql+psycopg",
        active_database_scheme="postgresql",
        using_sqlite_fallback=False,
        evidence_storage="POSTGRESQL",
    )
    pipeline = PipelineHealthResponse(
        source="pipeline_run_ledger",
        available=True,
        ready=True,
        paper_execution_allowed=True,
        pipeline={
            "id": "pipeline-1",
            "generation_id": "gen-1",
            "status": "COMPLETED",
            "execution_scope": "PAPER_ONLY",
            "started_at": datetime.utcnow(),
        },
        readiness={"required_stages": ["market"], "missing_stages": [], "failed_stages": []},
        lineage={"generation_id": "gen-1", "derived_row_counts": {"MarketFeatures": 18}, "verified": True},
    )
    fallback = PipelineHealthResponse(
        source="pipeline_run_ledger",
        available=False,
        ready=False,
        paper_execution_allowed=False,
        reason="SQLITE_FALLBACK",
    )

    assert health.status == "running"
    assert health.process_role == "all"
    assert health.admin_auth_required is False
    assert dependencies.active_database_scheme == "mssql"
    assert postgres_dependencies.evidence_storage == "POSTGRESQL"
    assert pipeline.lineage.verified is True
    assert fallback.paper_execution_allowed is False
