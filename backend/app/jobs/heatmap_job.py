from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.engines.liquidation_heatmap_engine import LiquidationHeatmapEngine

from app.repositories.heatmap_repository import HeatmapRepository

from app.database.models.market_candles import MarketCandle
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


def run_heatmap_job():

    print("Running Heatmap Engine")

    db = SessionLocal()
    try:
        symbols = SymbolRepository().get_active_symbols(db)

        for item in symbols:
            try:
                candle = (
                    db.query(MarketCandle)
                    .filter(MarketCandle.symbol == item.symbol)
                    .order_by(MarketCandle.candle_time.desc())
                    .first()
                )

                if not candle:

                    continue

                result = LiquidationHeatmapEngine().analyze(db, item.symbol, candle.close_price)

                # print(result)

                HeatmapRepository().save(db, result)
            except Exception as ex:
                if not is_transient_network_error(ex):
                    print(f"Heatmap job error {item.symbol}: {classify_network_error(ex)}")
                continue
    except Exception as ex:
        db.rollback()
        if not is_transient_network_error(ex):
            print("Heatmap job error:", classify_network_error(ex))
    finally:
        db.close()
