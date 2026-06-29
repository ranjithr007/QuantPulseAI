
from typing import Any
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

    # asyncio.run(LiquidationCollector().listen(save_event))
    return asyncio.run(
        run_liquidation_job_async(
            duration_seconds=None,
        )
    )


async def run_liquidation_job_async(
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """
    Starts the liquidation WebSocket collector.

    duration_seconds:
        None -> run continuously
        number -> stop after the specified number of seconds
    """

    print("Starting liquidation websocket")

    received_count = 0
    saved_count = 0
    last_event = None

    def save_event(event):
        nonlocal received_count
        nonlocal saved_count
        nonlocal last_event

        received_count += 1

        print("\n" + "=" * 80)
        print("LIQUIDATION EVENT RECEIVED")
        print("=" * 80)
        print(event)

        try:
            # =========================================================
            # Keep your existing database-save code here.
            # Do not replace your repository or model names.
            # =========================================================

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

            saved_count += 1
            last_event = event

            print("Liquidation event saved successfully")

        except Exception as error:
            print("Failed to save liquidation event:", error)
            raise

    collector = LiquidationCollector()

    try:
        listener = collector.listen(save_event)

        if duration_seconds is None:
            # Production mode: keep listening continuously.
            await listener

        else:
            # Manual-test mode: listen only for a limited time.
            await asyncio.wait_for(
                listener,
                timeout=duration_seconds,
            )

    except TimeoutError:
        print(
            f"\nLiquidation test window completed " f"after {duration_seconds} seconds"
        )

    except asyncio.CancelledError:
        print("Liquidation collector cancelled")
        raise

    return {
        "source": "binance_liquidation_websocket",
        "test_duration_seconds": duration_seconds,
        "received": received_count,
        "saved": saved_count,
        "last_event": (str(last_event) if last_event is not None else None),
    }
