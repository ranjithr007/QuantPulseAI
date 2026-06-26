from app.database.models.market_order_flow import MarketOrderFlow
from app.database.models.order_flow_signal import OrderFlowSignal
from app.repositories._db_utils import commit_or_rollback


class OrderFlowRepository:

    def save(self, db, data):

        signal = OrderFlowSignal(
            # -----------------
            # Symbol
            # -----------------
            symbol=data["symbol"],
            # -----------------
            # Volume / Delta
            # -----------------
            buy_volume=data["buy_volume"],
            sell_volume=data["sell_volume"],
            delta=data["delta"],
            cumulative_delta=data["cumulative_delta"],
            # -----------------
            # Pressure
            # -----------------
            buy_pressure=data["buy_pressure"],
            sell_pressure=data["sell_pressure"],
            aggressive_side=data["aggressive_side"],
            # -----------------
            # Whale Metrics
            # -----------------
            whale_buy_count=data["whale_buy_count"],
            whale_sell_count=data["whale_sell_count"],
            whale_buy_volume=data["whale_buy_volume"],
            whale_sell_volume=data["whale_sell_volume"],
            largest_trade_value=data["largest_trade_value"],
            # -----------------
            # Absorption
            # -----------------
            absorption_type=data["absorption_type"],
            absorption_strength=data["absorption_strength"],
            # -----------------
            # Exhaustion
            # -----------------
            exhaustion_type=data["exhaustion_type"],
            exhaustion_strength=data["exhaustion_strength"],
            # -----------------
            # Price Movement
            # -----------------
            start_price=data["start_price"],
            end_price=data["end_price"],
            price_change_pct=data["price_change_pct"],
            # -----------------
            # AI Score
            # -----------------
            orderflow_score=data["orderflow_score"],
            created_at=data["created_at"],
        )

        db.add(signal)

        commit_or_rollback(db)

    def latest(self, db, symbol):

        return (
            db.query(OrderFlowSignal)
            .filter(OrderFlowSignal.symbol == symbol)
            .order_by(OrderFlowSignal.created_at.desc())
            .first()
        )

    @staticmethod
    def save_orderflow(db, symbol, timeframe, data):

        cvd = data.get("cumulative_delta", data.get("cvd", data.get("delta", 0)))
        buyer_strength = data.get("buyer_strength", data.get("buyerStrength", 50))
        seller_strength = data.get("seller_strength", data.get("sellerStrength", 50))
        absorption = data.get("absorption", data.get("absorption_type", "NONE"))
        signal = data.get("signal", data.get("flow_signal", "NEUTRAL"))
        confidence = data.get("confidence", 0)

        record = MarketOrderFlow(
            Symbol=symbol,
            Timeframe=timeframe,
            BuyVolume=data.get("buy_volume", 0),
            SellVolume=data.get("sell_volume", 0),
            Delta=data.get("delta", 0),
            CVD=cvd,
            BuyerStrength=buyer_strength,
            SellerStrength=seller_strength,
            Absorption=absorption,
            Exhaustion="NONE",
            FlowSignal=signal,
            Confidence=confidence,
        )

        db.add(record)

        commit_or_rollback(db)

        return record

    def get_last_cvd(self, db, symbol):

        last = (
            db.query(OrderFlowSignal)
            .filter(OrderFlowSignal.symbol == symbol)
            .order_by(OrderFlowSignal.created_at.desc())
            .first()
        )

        if last is None:

            return 0

        return last.cumulative_delta

    def get_recent_flow(self, db, symbol, limit=5):

        return (
            db.query(OrderFlowSignal)
            .filter(OrderFlowSignal.symbol == symbol)
            .order_by(OrderFlowSignal.created_at.desc())
            .limit(limit)
            .all()
        )
