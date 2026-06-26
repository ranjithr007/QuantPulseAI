import asyncio

from app.database.sqlserver import SessionLocal

from app.collectors.binances.liquidation_collector import LiquidationCollector

from app.repositories.liquidation_repository import LiquidationRepository
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error
from app.repositories._db_utils import safe_rollback


def save_event(event):

    db = SessionLocal()

    try:

        # print("LIQ:", event)

        LiquidationRepository().save(db, event)

    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Liquidation save error:", summarize_network_error(ex))

    finally:

        db.close()


def run_liquidation_job():

    print("Starting liquidation websocket")

    asyncio.run(LiquidationCollector().listen(save_event))
