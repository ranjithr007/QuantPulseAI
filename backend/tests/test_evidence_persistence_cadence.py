import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime
from app.database.models.market_smc import MarketSMCSignal
from app.regimes.regime_service import run_regime_analysis
from app.repositories.feature_repository import save_market_feature
from app.repositories.smc_repository import SMCRepository


START = datetime(2026, 8, 28, 10, 0)


def _feature_payload(symbol="BTCUSDT", timeframe="1h"):
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "trend_score": 82.0,
        "momentum_score": 74.0,
        "volatility_score": 45.0,
        "liquidity_score": 60.0,
        "final_score": 78.0,
        "trend": "BULLISH",
        "signal": "BUY",
        "atr": 125.0,
        "data_generation_id": "generation-1",
    }


def _smc_payload(source_timestamp):
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "structure": "UPTREND",
        "bos": "BULLISH",
        "choch": "NONE",
        "liquidity_sweep": "NONE",
        "order_block_type": "BULLISH",
        "order_block_price": 100.0,
        "fvg_direction": "BULLISH",
        "fvg_size": 1.0,
        "smc_score": 75.0,
        "data_generation_id": "generation-1",
        "source_timestamp": source_timestamp,
    }


def test_feature_and_smc_rows_are_idempotent_per_final_candle():
    engine = create_engine("sqlite:///:memory:")
    MarketFeature.__table__.create(bind=engine)
    MarketSMCSignal.__table__.create(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        first_feature = save_market_feature(
            db,
            _feature_payload(),
            source_timestamp=START,
        )
        repeated_feature = save_market_feature(
            db,
            _feature_payload(),
            source_timestamp=START,
        )
        next_feature = save_market_feature(
            db,
            _feature_payload(),
            source_timestamp=START + timedelta(hours=1),
        )

        first_smc = SMCRepository().save(db, _smc_payload(START))
        repeated_smc = SMCRepository().save(db, _smc_payload(START))
        next_smc = SMCRepository().save(
            db,
            _smc_payload(START + timedelta(hours=1)),
        )

        assert first_feature.Id == repeated_feature.Id
        assert next_feature.Id != first_feature.Id
        assert db.query(MarketFeature).count() == 2
        assert first_feature.CreatedAt == START

        assert first_smc.id == repeated_smc.id
        assert next_smc.id != first_smc.id
        assert db.query(MarketSMCSignal).count() == 2
        assert first_smc.created_at == START
    finally:
        db.close()


def test_regime_dwell_advances_once_per_new_feature_candle():
    engine = create_engine("sqlite:///:memory:")
    MarketFeature.__table__.create(bind=engine)
    MarketRegime.__table__.create(bind=engine)
    session_factory = sessionmaker(bind=engine)

    db = session_factory()
    save_market_feature(db, _feature_payload(), source_timestamp=START)
    db.close()

    with patch(
        "app.regimes.regime_service.SessionLocal",
        side_effect=session_factory,
    ), patch(
        "app.regimes.regime_service.SymbolRepository.get_active_symbols",
        return_value=[SimpleNamespace(symbol="BTCUSDT")],
    ):
        first = run_regime_analysis()
        repeated = run_regime_analysis()

        db = session_factory()
        save_market_feature(
            db,
            _feature_payload(),
            source_timestamp=START + timedelta(hours=1),
        )
        db.close()
        second_candle = run_regime_analysis()

    db = session_factory()
    try:
        records = db.query(MarketRegime).order_by(MarketRegime.Id.asc()).all()
        assert len(records) == 2
        assert records[0].CreatedAt == START
        assert records[1].CreatedAt == START + timedelta(hours=1)
        assert json.loads(records[0].Reason)["dwell_cycles"] == 1
        assert json.loads(records[1].Reason)["dwell_cycles"] == 2
        assert first[0]["dwell_cycles"] == 1
        assert repeated[0]["dwell_cycles"] == 1
        assert repeated[0]["persisted"] is False
        assert second_candle[0]["dwell_cycles"] == 2
    finally:
        db.close()
