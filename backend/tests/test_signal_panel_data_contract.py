from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.market_smc import MarketSMCSignal
from app.intelligence.contradiction_engine import _direction_from_smc
from app.orderflow.orderflow_engine import analyze_orderflow
from app.repositories.smc_repository import SMCRepository


class Candle:
    def __init__(self, open_price, close_price, high_price, low_price, volume):
        self.open_price = open_price
        self.close_price = close_price
        self.high_price = high_price
        self.low_price = low_price
        self.volume = volume


def test_orderflow_engine_marks_negative_delta_as_sellers_control():
    candles = [
        Candle(10, 9, 11, 8, 100),
        Candle(9, 8, 9, 7, 120),
        Candle(8, 8.5, 10, 8, 30),
    ]

    result = analyze_orderflow(candles)

    assert result["delta"] < 0
    assert result["buyer_strength"] == 25
    assert result["seller_strength"] == 75
    assert result["signal"] == "SELLERS_CONTROL"
    assert result["confidence"] == 50


def test_smc_repository_derives_directional_bias_from_score():
    engine = create_engine("sqlite:///:memory:")
    MarketSMCSignal.__table__.create(bind=engine)
    db = sessionmaker(bind=engine)()

    try:
        record = SMCRepository().save(
            db,
            {
                "symbol": "DOGEUSDT",
                "timeframe": "4h",
                "structure": "RANGE",
                "bos": "NONE",
                "choch": "NONE",
                "liquidity_sweep": "SELL_SIDE_SWEEP",
                "order_block_type": "NONE",
                "order_block_price": 0,
                "fvg_direction": "NONE",
                "fvg_size": 0,
                "smc_score": 36.36,
            },
        )

        assert record.smc_bias == "SHORT"
        assert db.query(MarketSMCSignal).first().smc_bias == "SHORT"
    finally:
        db.close()


def test_contradiction_engine_accepts_long_short_smc_bias_values():
    assert _direction_from_smc(type("Obj", (), {"smc_bias": "LONG"})()) == "LONG"
    assert _direction_from_smc(type("Obj", (), {"smc_bias": "SHORT"})()) == "SHORT"
