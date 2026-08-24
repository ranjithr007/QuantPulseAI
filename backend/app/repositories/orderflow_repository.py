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

    def latest(self, db, symbol, timeframe=None):
        if timeframe:
            latest_market_orderflow = (
                db.query(MarketOrderFlow)
                .filter(
                    MarketOrderFlow.Symbol == symbol,
                    MarketOrderFlow.Timeframe == timeframe,
                )
                .order_by(MarketOrderFlow.CreatedAt.desc(), MarketOrderFlow.Id.desc())
                .first()
            )
            if latest_market_orderflow is not None:
                return latest_market_orderflow

        query = db.query(OrderFlowSignal).filter(OrderFlowSignal.symbol == symbol)

        return query.order_by(OrderFlowSignal.created_at.desc(), OrderFlowSignal.id.desc()).first()

    @staticmethod
    def save_orderflow(db, symbol, timeframe, data):
        record = MarketOrderFlow(
            Symbol=symbol,
            Timeframe=timeframe,            
            BuyVolume=data["buy_volume"],
            SellVolume=data["sell_volume"],
            Delta=data["delta"],
            CVD=data.get("cumulative_delta", data.get("cvd", 0)),
            BuyerStrength=data["buyer_strength"],
            SellerStrength=data["seller_strength"],
            Absorption=data["absorption"],
            Exhaustion=data["exhaustion"],
            FlowSignal=data["signal"],
            Confidence=data["confidence"],
            data_generation_id=data.get("data_generation_id"),
        )

        db.add(record)

        commit_or_rollback(db)

        return record

    def get_last_cvd(self, db, symbol):
        latest_market_orderflow = (
            db.query(MarketOrderFlow)
            .filter(MarketOrderFlow.Symbol == symbol)
            .order_by(MarketOrderFlow.CreatedAt.desc(), MarketOrderFlow.Id.desc())
            .first()
        )

        if latest_market_orderflow is not None and latest_market_orderflow.CVD is not None:
            return latest_market_orderflow.CVD

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
