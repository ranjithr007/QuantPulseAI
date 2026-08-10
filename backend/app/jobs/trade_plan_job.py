from app.database.sqlserver import SessionLocal


from app.repositories.fusion_signal_repository import FusionSignalRepository


from app.repositories.feature_repository import get_latest_feature


from app.repositories.trade_plan_repository import TradePlanRepository


from app.services.market_price_service import MarketPriceService


from app.trading.planner.trade_planner import TradePlanner
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES

fusion_repo = FusionSignalRepository()

TRADE_PLAN_TIMEFRAMES = list(OFFICIAL_ENTRY_TIMEFRAMES)

trade_repo = TradePlanRepository()

price_service = MarketPriceService()

planner = TradePlanner()


def run_trade_plan_job():

    print("Trade Planner Running...")

    db = SessionLocal()

    try:

        for timeframe in TRADE_PLAN_TIMEFRAMES:
            signals = fusion_repo.get_latest_tradeable_signals(db, timeframe)

            for signal in signals:
                try:
                    signal_timeframe = getattr(signal, "timeframe", None) or timeframe
                    price = price_service.get_latest_price(signal.symbol)

                    if price is None:
                        continue

                    feature = get_latest_feature(db, signal.symbol, signal_timeframe)

                    if feature is None:
                        continue

                    ai_signal = {
                        "symbol": signal.symbol,
                        "decision": signal.decision,
                        "confidence": signal.confidence,
                        "timeframe": signal_timeframe,
                    }

                    plan = planner.create_plan(ai_signal, price, feature.ATR)
                    plan["entry_timeframe"] = signal_timeframe

                    if trade_repo.has_open_trade(db, plan["symbol"], plan["side"]):

                        print("Trade already exists", plan["symbol"], signal_timeframe)

                        continue

                    trade_repo.save_trade_plan(db, plan)

                    print("New Trade Created", signal_timeframe, plan)
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(f"Trade plan job error {signal.symbol} {getattr(signal, 'timeframe', None) or timeframe}: {summarize_network_error(ex)}")
                    continue
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Trade plan job error:", summarize_network_error(ex))

    finally:

        db.close()
