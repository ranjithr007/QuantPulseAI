from app.database.sqlserver import SessionLocal


from app.repositories.fusion_signal_repository import FusionSignalRepository


from app.repositories.feature_repository import get_latest_feature


from app.repositories.trade_plan_repository import TradePlanRepository


from app.services.market_price_service import MarketPriceService


from app.trading.planner.trade_planner import TradePlanner

fusion_repo = FusionSignalRepository()

trade_repo = TradePlanRepository()

price_service = MarketPriceService()

planner = TradePlanner()


def run_trade_plan_job():

    print("Trade Planner Running...")

    db = SessionLocal()

    try:

        signals = fusion_repo.get_latest_tradeable_signals(db)

        for signal in signals:

            price = price_service.get_latest_price(signal.symbol)

            if price is None:
                continue

            feature = get_latest_feature(db, signal.symbol)

            if feature is None:
                continue

            ai_signal = {
                "symbol": signal.symbol,
                "decision": signal.decision,
                "confidence": signal.confidence,
            }

            plan = planner.create_plan(ai_signal, price, feature.ATR)

            if trade_repo.has_open_trade(db, plan["symbol"], plan["side"]):

                print("Trade already exists", plan["symbol"])

                continue

            trade_repo.save_trade_plan(db, plan)

            print("New Trade Created", plan)

    finally:

        db.close()