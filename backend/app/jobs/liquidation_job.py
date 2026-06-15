import asyncio

from app.database.sqlserver import SessionLocal

from app.collectors.binances.liquidation_collector import LiquidationCollector

from app.repositories.liquidation_repository import LiquidationRepository


def save_event(event):

    db = SessionLocal()

    try:

        # print("LIQ:", event)

        LiquidationRepository().save(db, event)

    finally:

        db.close()


def run_liquidation_job():

    print("Starting liquidation websocket")

    asyncio.run(LiquidationCollector().listen(save_event))