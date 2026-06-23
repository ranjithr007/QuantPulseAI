from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.risk_decision import RiskDecision
from app.repositories.risk_repository import RiskRepository


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
