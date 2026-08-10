from app.database.sqlserver import SessionLocal
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.repositories.candle_repository import get_latest_candle
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


DEFAULT_TIMEFRAME = "5m"


def run_paper_trade_monitor_job():
    db = SessionLocal()
    try:
        summary = {
            "processed": 0,
            "closed": 0,
            "wins": 0,
            "losses": 0,
            "still_open": 0,
            "skipped": 0,
            "errors": [],
            "records": [],
        }
        repo = PaperTradeRepository()
        for trade in repo.get_open_trades(db):
            summary["processed"] += 1
            try:
                timeframe = getattr(trade, "entry_timeframe", None) or DEFAULT_TIMEFRAME
                candle = get_latest_candle(db, trade.symbol, timeframe)

                if candle is None:
                    summary["skipped"] += 1
                    summary["errors"].append(
                        f"No latest candle for {trade.symbol} {timeframe}"
                    )
                    continue

                decision = evaluate_paper_trade_exit(trade, candle)

                if decision["action"] == "HOLD":
                    summary["still_open"] += 1
                    summary["records"].append(decision)
                    continue

                closed_trade = repo.close_trade(
                    db,
                    trade,
                    decision["exit_price"],
                    decision["result"],
                    fill_profile=decision.get("fill_profile"),
                )
                summary["closed"] += 1

                if decision["result"] == "WIN":
                    summary["wins"] += 1
                else:
                    summary["losses"] += 1

                summary["records"].append(
                    {
                        **decision,
                        "paper_trade_id": closed_trade.id,
                        "pnl_percent": closed_trade.pnl_percent,
                    }
                )
            except Exception as ex:
                summary["errors"].append(
                    f"{trade.symbol}: {summarize_network_error(ex)}"
                )
                continue

        print("Paper Trade Monitor Completed", summary)
        return summary

    except Exception as ex:
        safe_rollback(db)
        summary["errors"].append(summarize_network_error(ex))
        if not is_transient_network_error(ex):
            print("Paper trade monitor job error:", summarize_network_error(ex))
        return summary

    finally:
        db.close()
