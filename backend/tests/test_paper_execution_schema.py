from sqlalchemy import create_engine, inspect, text

from app.database.paper_execution_schema import ensure_paper_execution_schema


def test_ensure_paper_execution_schema_adds_missing_columns_idempotently():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, "
                "strategy_id VARCHAR(50), strategy_version VARCHAR(50), "
                "created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE strategy_shadow_trades (id INTEGER PRIMARY KEY, "
                "strategy_id VARCHAR(50), strategy_version VARCHAR(50), "
                "created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE decision_snapshots ("
                "id INTEGER PRIMARY KEY, strategy_id VARCHAR(50), "
                "strategy_version VARCHAR(50), decision_version VARCHAR(40), "
                "symbol VARCHAR(30), created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE trade_plans (id INTEGER PRIMARY KEY, "
                "strategy_id VARCHAR(50), strategy_version VARCHAR(50), "
                "created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE risk_decisions (id INTEGER PRIMARY KEY, "
                "strategy_id VARCHAR(50), strategy_version VARCHAR(50), "
                "created_at DATETIME)"
            )
        )

    assert ensure_paper_execution_schema(engine) is True
    assert ensure_paper_execution_schema(engine) is False

    assert inspect(engine).has_table("fast_exit_heartbeats")

    for table_name in ("paper_trades", "strategy_shadow_trades"):
        columns = {item["name"] for item in inspect(engine).get_columns(table_name)}
        assert {
            "trailing_activation_r",
            "execution_evidence_json",
            "exit_evidence_json",
        } <= columns

    indexes = {
        item["name"]
        for item in inspect(engine).get_indexes("decision_snapshots")
    }
    assert "ix_decision_snapshots_opportunity_history" in indexes

    expected_strategy_indexes = {
        "decision_snapshots": "ix_decision_snapshots_strategy_summary",
        "trade_plans": "ix_trade_plans_strategy_summary",
        "risk_decisions": "ix_risk_decisions_strategy_summary",
        "paper_trades": "ix_paper_trades_strategy_summary",
        "strategy_shadow_trades": "ix_strategy_shadow_trades_strategy_summary",
    }
    for table_name, index_name in expected_strategy_indexes.items():
        indexes = {
            item["name"] for item in inspect(engine).get_indexes(table_name)
        }
        assert index_name in indexes
