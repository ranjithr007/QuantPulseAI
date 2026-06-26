from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.market_order_flow import MarketOrderFlow
from app.repositories.orderflow_repository import OrderFlowRepository


def test_save_orderflow_handles_engine_payload_and_class_call():
    engine = create_engine("sqlite:///:memory:")
    MarketOrderFlow.__table__.create(bind=engine)
    db = sessionmaker(bind=engine)()

    try:
        payload = {
            "buy_volume": 12.5,
            "sell_volume": 7.5,
            "delta": 5.0,
            "cumulative_delta": 15.0,
            "buyer_strength": 75,
            "seller_strength": 25,
            "absorption": "BUY_ABSORPTION",
            "signal": "BUYERS_CONTROL",
            "confidence": 50,
            "created_at": datetime.utcnow(),
        }

        record = OrderFlowRepository.save_orderflow(db, "BTCUSDT", "5m", payload)

        saved = db.query(MarketOrderFlow).first()

        assert record.Id == saved.Id
        assert saved.Symbol == "BTCUSDT"
        assert saved.Timeframe == "5m"
        assert saved.CVD == 15.0
        assert saved.BuyerStrength == 75
        assert saved.SellerStrength == 25
        assert saved.Absorption == "BUY_ABSORPTION"
        assert saved.FlowSignal == "BUYERS_CONTROL"
        assert saved.Confidence == 50
    finally:
        db.close()


def test_save_orderflow_falls_back_to_delta_and_neutral_defaults():
    engine = create_engine("sqlite:///:memory:")
    MarketOrderFlow.__table__.create(bind=engine)
    db = sessionmaker(bind=engine)()

    try:
        record = OrderFlowRepository.save_orderflow(
            db,
            "ETHUSDT",
            "15m",
            {"buy_volume": 1.0, "sell_volume": 2.0, "delta": -1.0},
        )

        saved = db.query(MarketOrderFlow).first()

        assert record.Id == saved.Id
        assert saved.CVD == -1.0
        assert saved.BuyerStrength == 50
        assert saved.SellerStrength == 50
        assert saved.Absorption == "NONE"
        assert saved.FlowSignal == "NEUTRAL"
        assert saved.Confidence == 0
    finally:
        db.close()
