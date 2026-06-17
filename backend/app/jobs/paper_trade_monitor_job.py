from app.database.sqlserver import SessionLocal
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.repositories.candle_repository import get_latest_candle
from app.repositories.paper_trade_repository import PaperTradeRepository


DEFAULT_TIMEFRAME = "5m"


def run_paper_trade_monitor_job():
    db = SessionLocal()
    repo = PaperTradeRepository()
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

    try:
        for trade in repo.get_open_trades(db):
            summary["processed"] += 1
            candle = get_latest_candle(db, trade.symbol, DEFAULT_TIMEFRAME)

            if candle is None:
                summary["skipped"] += 1
                summary["errors"].append(
                    f"No latest candle for {trade.symbol} {DEFAULT_TIMEFRAME}"
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

        print("Paper Trade Monitor Completed", summary)
        return summary

    finally:
        db.close()
