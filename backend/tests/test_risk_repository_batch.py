from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.database.models.risk_decision import RiskDecision
from app.repositories.risk_repository import RiskRepository
from app.repositories.trade_thesis_repository import ensure_trade_thesis_lineage_schema


def test_latest_for_symbols_returns_latest_decision_for_each_symbol():
    engine = create_engine("sqlite:///:memory:")
    RiskDecision.__table__.create(bind=engine)
    session = sessionmaker(bind=engine)()
    now = datetime.utcnow()

    try:
        session.add_all(
            [
                RiskDecision(
                    symbol="BTCUSDT",
                    signal="LONG",
                    decision="WAIT",
                    created_at=now - timedelta(minutes=1),
                ),
                RiskDecision(
                    symbol="BTCUSDT",
                    signal="LONG",
                    decision="APPROVE",
                    created_at=now,
                ),
                RiskDecision(
                    symbol="ETHUSDT",
                    signal="SHORT",
                    decision="REJECT",
                    created_at=now,
                ),
            ]
        )
        session.commit()

        latest = RiskRepository().latest_for_symbols(
            session,
            ["BTCUSDT", "ETHUSDT", "MISSING"],
        )

        assert set(latest) == {"BTCUSDT", "ETHUSDT"}
        assert latest["BTCUSDT"].decision == "APPROVE"
        assert latest["ETHUSDT"].decision == "REJECT"
    finally:
        session.close()


def test_latest_for_symbols_handles_empty_input_without_querying():
    assert RiskRepository().latest_for_symbols(None, []) == {}


def test_save_persists_point_in_time_decision_snapshot():
    fake_db = SimpleNamespace()
    fake_db.add = lambda *args, **kwargs: None
    fake_db.flush = lambda: None
    fake_db.close = lambda: None
    fake_db.execute = lambda *args, **kwargs: SimpleNamespace(inserted_primary_key=(77,))

    with patch("app.repositories.risk_repository.SessionLocal", return_value=fake_db), patch(
        "app.repositories.risk_repository.persist_decision_snapshot",
        side_effect=lambda db, snapshot: SimpleNamespace(id=77),
    ) as persist_snapshot, patch(
        "app.repositories.risk_repository.build_decision_snapshot",
        return_value={"decision": "TAKE_TRADE"},
    ):
        RiskRepository().save(
            {
                "symbol": "BTCUSDT",
                "signal": "LONG",
                "decision": "TAKE_TRADE",
                "entry": 100.0,
                "stop_loss": 99.0,
                "targets": {"t1": 102.0, "t2": 103.0},
                "position_size": 1.0,
                "risk_reward": 2.0,
                "confidence": 80.0,
                "risk_percent": 1.0,
            }
        )

    assert persist_snapshot.called


def test_save_works_when_risk_decisions_table_has_no_thesis_id_column():
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    session.execute(
        text(
            """
            CREATE TABLE risk_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol VARCHAR(30) NOT NULL,
                signal VARCHAR(20),
                decision VARCHAR(40),
                entry_price FLOAT,
                stop_loss FLOAT,
                target1 FLOAT,
                target2 FLOAT,
                risk_reward FLOAT,
                position_size FLOAT,
                risk_percent FLOAT,
                confidence FLOAT,
                created_at DATETIME NOT NULL
            )
            """
        )
    )
    session.commit()

    thesis_calls = []

    try:
        with patch("app.repositories.risk_repository.SessionLocal", return_value=session), patch(
            "app.repositories.risk_repository.persist_decision_snapshot",
            side_effect=lambda db, snapshot: db.commit() or SimpleNamespace(id=88),
        ), patch(
            "app.repositories.risk_repository.TradeThesisRepository.attach_risk_decision",
            side_effect=lambda db, thesis_id, risk_decision_id, commit=False: thesis_calls.append(
                (thesis_id, risk_decision_id, commit)
            ),
        ):
            RiskRepository().save(
                {
                    "symbol": "BTCUSDT",
                    "signal": "LONG",
                    "decision": "TAKE_TRADE",
                    "entry": 100.0,
                    "stop_loss": 99.0,
                    "targets": {"t1": 102.0, "t2": 103.0},
                    "position_size": 1.0,
                    "risk_reward": 2.0,
                    "confidence": 80.0,
                    "risk_percent": 1.0,
                    "thesis_id": 123,
                }
            )

        row = session.execute(
            text("SELECT symbol, decision, entry_price, stop_loss FROM risk_decisions")
        ).first()

        assert row is not None
        assert row._mapping["symbol"] == "BTCUSDT"
        assert row._mapping["decision"] == "TAKE_TRADE"
        assert row._mapping["entry_price"] == 100.0
        assert thesis_calls and thesis_calls[0][0] == 123
    finally:
        session.close()


def test_ensure_trade_thesis_lineage_schema_adds_missing_thesis_id_column():
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    for ddl in (
        """
        CREATE TABLE trade_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR(30) NOT NULL,
            created_at DATETIME NOT NULL
        )
        """,
        """
        CREATE TABLE risk_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR(30) NOT NULL,
            created_at DATETIME NOT NULL
        )
        """,
        """
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR(30) NOT NULL,
            created_at DATETIME NOT NULL
        )
        """,
    ):
        session.execute(text(ddl))
    session.commit()

    try:
        ensure_trade_thesis_lineage_schema(engine)

        inspector = inspect(engine)
        for table_name, index_name in (
            ("trade_plans", "ix_trade_plans_thesis_id"),
            ("risk_decisions", "ix_risk_decisions_thesis_id"),
            ("paper_trades", "ix_paper_trades_thesis_id"),
        ):
            columns = [column["name"] for column in inspector.get_columns(table_name)]
            indexes = [index["name"] for index in inspector.get_indexes(table_name)]

            assert "thesis_id" in columns
            assert index_name in indexes
    finally:
        session.close()
