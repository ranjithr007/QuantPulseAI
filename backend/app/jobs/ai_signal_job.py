from app.database.sqlserver import SessionLocal
from app.engines.smart_money_engine import SmartMoneyEngine
from app.repositories.ai_signal_repository import AISignalRepository
from app.database.models.liquidity_signals import LiquiditySignal
from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_ai_signal_job():

    print("Running Smart Money AI")

    db = SessionLocal()

    try:
        liquidity = (
            db.query(LiquiditySignal).order_by(LiquiditySignal.created_at.desc()).first()
        )

        heatmap = (
            db.query(LiquidationHeatmap)
            .order_by(LiquidationHeatmap.created_at.desc())
            .first()
        )

        if liquidity and heatmap:

            result = SmartMoneyEngine().analyze(liquidity, heatmap)

            result["symbol"] = liquidity.symbol
            result["timeframe"] = "5m"

            result["entry_price"] = heatmap.current_price

            result["target_price"] = heatmap.target_price

            # print(result)

            AISignalRepository().save(db, result)
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("AI signal job error:", summarize_network_error(ex))
    except Exception as ex:
        if not is_transient_network_error(ex):
            print("AI signal job error:", summarize_network_error(ex))
    finally:
        db.close()
