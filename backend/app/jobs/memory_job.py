from app.database.sqlserver import SessionLocal

from app.intelligence.memory.trade_memory_engine import TradeMemoryEngine

from app.repositories.trade_plan_repository import TradePlanRepository

from app.services.market_price_service import MarketPriceService
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error

memory = TradeMemoryEngine()

repo = TradePlanRepository()

price_service = MarketPriceService()


def run_memory_job():

    db = SessionLocal()

    try:

        print("🧠 AI Memory Engine Running...")

        trades = repo.get_open_trades(db)

        results = memory.process(db, trades, price_service.get_latest_price)

        print(f"Memory updated {len(results)} trades")
    except Exception as ex:
        db.rollback()
        if not is_transient_network_error(ex):
            print("Memory job error:", summarize_network_error(ex))

    finally:

        db.close()
