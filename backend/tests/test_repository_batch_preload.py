from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.market_candles import MarketCandle
from app.database.models.market_features import MarketFeature
from app.database.models.market_order_flow import MarketOrderFlow
from app.database.models.market_regimes import MarketRegime
from app.database.models.market_smc import MarketSMCSignal
from app.repositories.candle_repository import get_latest_candle, prime_latest_candle_cache
from app.repositories.intelligence_repository import get_ai_inputs, prime_ai_inputs_cache


def test_latest_candle_batch_preload_populates_each_symbol_cache():
    engine, db = _session_for(MarketCandle)
    now = datetime.utcnow().replace(microsecond=0)
    try:
        db.add_all(
            [
                _candle(1, "BTCUSDT", now - timedelta(hours=2), 100),
                _candle(2, "BTCUSDT", now - timedelta(hours=1), 105),
                _candle(3, "ETHUSDT", now - timedelta(hours=1), 55),
            ]
        )
        db.commit()

        prime_latest_candle_cache(db, ["BTCUSDT", "ETHUSDT"], "1h")

        assert get_latest_candle(db, "BTCUSDT", "1h").close_price == 105
        assert get_latest_candle(db, "ETHUSDT", "1h").close_price == 55
    finally:
        db.close()
        engine.dispose()


def test_ai_input_batch_preload_selects_latest_row_per_symbol():
    models = (MarketFeature, MarketRegime, MarketOrderFlow, MarketSMCSignal)
    engine = create_engine("sqlite:///:memory:")
    for model in models:
        model.__table__.create(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        db.add_all(
            [
                MarketFeature(Id=1, Symbol="BTCUSDT", Timeframe="1h", TrendScore=40),
                MarketFeature(Id=2, Symbol="BTCUSDT", Timeframe="1h", TrendScore=62),
                MarketFeature(Id=3, Symbol="ETHUSDT", Timeframe="1h", TrendScore=53),
                MarketRegime(Id=1, Symbol="BTCUSDT", Timeframe="1h", Regime="BULLISH"),
                MarketRegime(Id=2, Symbol="ETHUSDT", Timeframe="1h", Regime="NEUTRAL"),
                MarketOrderFlow(Id=1, Symbol="BTCUSDT", Timeframe="1h", Delta=10),
                MarketOrderFlow(Id=2, Symbol="ETHUSDT", Timeframe="1h", Delta=-5),
                MarketSMCSignal(id=1, symbol="BTCUSDT", timeframe="1h", smc_bias="LONG"),
                MarketSMCSignal(id=2, symbol="ETHUSDT", timeframe="1h", smc_bias="SHORT"),
            ]
        )
        db.commit()

        prime_ai_inputs_cache(db, ["BTCUSDT", "ETHUSDT"], "1h")

        assert get_ai_inputs(db, "BTCUSDT", "1h")["feature"].TrendScore == 62
        assert get_ai_inputs(db, "ETHUSDT", "1h")["smc"].smc_bias == "SHORT"
    finally:
        db.close()
        engine.dispose()


def _session_for(*models):
    engine = create_engine("sqlite:///:memory:")
    for model in models:
        model.__table__.create(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _candle(identifier, symbol, open_time, close_price):
    return MarketCandle(
        id=identifier,
        symbol=symbol,
        timeframe="1h",
        venue="BINANCE",
        market_type="FUTURES",
        open_price=close_price,
        high_price=close_price,
        low_price=close_price,
        close_price=close_price,
        volume=1,
        candle_time=open_time,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=59),
        is_final=True,
        source="TEST",
        revision=0,
        quality_state="VERIFIED",
    )
