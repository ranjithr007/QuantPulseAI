from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.engines.liquidation_heatmap_engine import LiquidationHeatmapEngine

from app.repositories.heatmap_repository import HeatmapRepository

from app.database.models.market_candles import MarketCandle


def run_heatmap_job():

    print("Running Heatmap Engine")

    db = SessionLocal()

    symbols = SymbolRepository().get_active_symbols(db)

    for item in symbols:

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

    db.close()