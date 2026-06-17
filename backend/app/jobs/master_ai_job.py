from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.engines.master_ai_engine import MasterAIEngine
from app.repositories.candle_repository import get_latest_candles

from app.repositories.master_signal_repository import MasterSignalRepository
from app.database.models.liquidity_signals import LiquiditySignal
from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.database.models.whale_signals import WhaleSignal
from app.engines.atr_engine import ATREngine
from app.trading.trade_plan_engine import build_trade_plan


def run_master_ai_job():

    print("Running Master AI Engine")

    db = SessionLocal()

    try:

        symbols = SymbolRepository().get_active_symbols(db)

        engine = MasterAIEngine()

        master_repo = MasterSignalRepository()
        atr_engine = ATREngine()

        for item in symbols:

            symbol = item.symbol

            liquidity = (
                db.query(LiquiditySignal)
                .filter(LiquiditySignal.symbol == symbol)
                .order_by(LiquiditySignal.created_at.desc())
                .first()
            )

            heatmap = (
                db.query(LiquidationHeatmap)
                .filter(LiquidationHeatmap.symbol == symbol)
                .order_by(LiquidationHeatmap.created_at.desc())
                .first()
            )

            whale = (
                db.query(WhaleSignal)
                .filter(WhaleSignal.symbol == symbol)
                .order_by(WhaleSignal.created_at.desc())
                .first()
            )

            if not liquidity:
                print("No liquidity:", symbol)
                continue

            if not heatmap:
                print("No heatmap:", symbol)
                continue

            if not whale:
                print("No whale:", symbol)
                continue
            candles = get_latest_candles(db, symbol, "5m", 100)

            current_price = heatmap.current_price
            atr = atr_engine.calculate(candles) or current_price * 0.01

            result = engine.analyze(
                db,
                symbol,
                liquidity,
                heatmap,
                whale,
                current_price,
                atr,
            )

            trade_plan = build_trade_plan(result["signal"], current_price, atr)
            result["entry_price"] = trade_plan["entry"]
            result["target_price"] = trade_plan["target1"]

            master_repo.save(db, result)

            print("Master AI saved:", symbol, result["signal"], result["confidence"])

    except Exception as e:

        print("Master AI Error:", e)

    finally:

        db.close()
