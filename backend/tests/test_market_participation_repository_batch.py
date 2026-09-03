from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.repositories.market_participation_repository import (
    MARKET_PARTICIPATION_DECISION_VERSION,
    MARKET_PARTICIPATION_TIMEFRAME,
    MarketParticipationRepository,
)


def test_latest_for_symbols_returns_one_latest_row_per_symbol():
    engine = create_engine("sqlite:///:memory:")
    DecisionSnapshot.__table__.create(bind=engine)
    session = sessionmaker(bind=engine)()
    now = datetime.utcnow()
    try:
        session.add_all(
            [
                _snapshot("BTCUSDT", now - timedelta(minutes=5), 41),
                _snapshot("BTCUSDT", now, 62),
                _snapshot("ETHUSDT", now - timedelta(minutes=1), 53),
                _snapshot(
                    "BTCUSDT",
                    now + timedelta(minutes=1),
                    99,
                    decision_version="unrelated_version",
                ),
            ]
        )
        session.commit()

        result = MarketParticipationRepository().latest_for_symbols(
            session,
            ["ethusdt", "BTCUSDT", "BTCUSDT"],
        )

        assert set(result) == {"BTCUSDT", "ETHUSDT"}
        assert result["BTCUSDT"]["confidence"] == 62
        assert result["ETHUSDT"]["confidence"] == 53
    finally:
        session.close()
        engine.dispose()


def _snapshot(symbol, timestamp, confidence, *, decision_version=None):
    return DecisionSnapshot(
        symbol=symbol,
        timeframe=MARKET_PARTICIPATION_TIMEFRAME,
        source_timestamp=timestamp,
        effective_timestamp=timestamp,
        feature_version="spot_participation_features_v1",
        decision_version=decision_version or MARKET_PARTICIPATION_DECISION_VERSION,
        quality_state="OK",
        decision="BULLISH",
        confidence=confidence,
        snapshot_json="{}",
        created_at=timestamp,
    )
