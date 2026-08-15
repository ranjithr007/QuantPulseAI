from app.database.sqlserver import SessionLocal
from app.paper_trading.exit_policy import PAPER_EXIT_MONITOR_TIMEFRAME
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.repositories.candle_repository import get_final_candles_after
from app.repositories.candle_repository import get_latest_candle
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories._db_utils import safe_rollback
from app.utils.freshness import normalize_timestamp_to_utc
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


DEFAULT_TIMEFRAME = PAPER_EXIT_MONITOR_TIMEFRAME
EXIT_CANDLE_LOOKBACK_LIMIT = 1000


def run_paper_trade_monitor_job():
    db = SessionLocal()
    try:
        summary = {
            "processed": 0,
            "policy_updates": 0,
            "closed": 0,
            "partial_closes": 0,
            "wins": 0,
            "losses": 0,
            "still_open": 0,
            "skipped": 0,
            "candles_evaluated": 0,
            "entry_timeframe_fallbacks": 0,
            "errors": [],
            "records": [],
        }
        repo = PaperTradeRepository()
        for trade in repo.get_open_trades(db):
            summary["processed"] += 1
            try:
                if repo.ensure_staged_exit_policy(db, trade):
                    summary["policy_updates"] += 1
                candles, timeframe, used_fallback, source_available = _exit_candles(
                    db,
                    trade,
                )
                if used_fallback:
                    summary["entry_timeframe_fallbacks"] += 1

                if not source_available:
                    summary["skipped"] += 1
                    summary["errors"].append(
                        f"No latest candle for {trade.symbol} {timeframe}"
                    )
                    continue

                if not candles:
                    summary["still_open"] += 1
                    summary["records"].append(
                        {
                            "paper_trade_id": trade.id,
                            "symbol": trade.symbol,
                            "side": trade.side,
                            "action": "HOLD",
                            "result": "OPEN",
                            "reason": "NO_NEW_CLOSED_EXIT_CANDLE",
                            "monitor_timeframe": timeframe,
                        }
                    )
                    continue

                last_evaluated_at = None
                last_decision = None
                trade_closed = False
                for candle in candles:
                    decision = {
                        **evaluate_paper_trade_exit(trade, candle),
                        "monitor_timeframe": timeframe,
                    }
                    summary["candles_evaluated"] += 1
                    last_evaluated_at = _candle_checkpoint(candle)
                    last_decision = decision

                    if decision["action"] == "HOLD":
                        continue

                    if decision["action"] == "PARTIAL_CLOSE":
                        updated_trade = repo.apply_target1(
                            db,
                            trade,
                            decision["exit_price"],
                            candle_time=decision.get("candle_time"),
                            evaluated_at=last_evaluated_at,
                        )
                        summary["partial_closes"] += 1
                        summary["records"].append(
                            {
                                **decision,
                                "paper_trade_id": updated_trade.id,
                                "stop_loss": updated_trade.stop_loss,
                                "target1_hit_at": updated_trade.target1_hit_at,
                            }
                        )
                        continue

                    closed_trade = repo.close_trade(
                        db,
                        trade,
                        decision["exit_price"],
                        decision["result"],
                        fill_profile=decision.get("fill_profile"),
                    )
                    summary["closed"] += 1
                    trade_closed = True

                    if closed_trade.result == "WIN":
                        summary["wins"] += 1
                    else:
                        summary["losses"] += 1

                    summary["records"].append(
                        {
                            **decision,
                            "paper_trade_id": closed_trade.id,
                            "result": closed_trade.result,
                            "pnl_percent": closed_trade.pnl_percent,
                        }
                    )
                    break

                if not trade_closed:
                    if last_evaluated_at is not None:
                        repo.mark_exit_evaluated(db, trade, last_evaluated_at)
                    summary["still_open"] += 1
                    if last_decision and last_decision["action"] == "HOLD":
                        summary["records"].append(last_decision)
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


def _exit_candles(db, trade):
    preferred = (
        getattr(trade, "exit_monitor_timeframe", None)
        or DEFAULT_TIMEFRAME
    )
    checkpoint = normalize_timestamp_to_utc(
        getattr(trade, "last_exit_evaluated_at", None)
        or getattr(trade, "opened_at", None)
    )
    candles = get_final_candles_after(
        db,
        trade.symbol,
        preferred,
        checkpoint,
        limit=EXIT_CANDLE_LOOKBACK_LIMIT,
    )
    timeframe = preferred
    used_fallback = False
    source_available = bool(candles) or get_latest_candle(
        db,
        trade.symbol,
        preferred,
    ) is not None

    entry_timeframe = getattr(trade, "entry_timeframe", None)
    if not candles and entry_timeframe and entry_timeframe != preferred:
        candles = get_final_candles_after(
            db,
            trade.symbol,
            entry_timeframe,
            checkpoint,
            limit=EXIT_CANDLE_LOOKBACK_LIMIT,
        )
        timeframe = entry_timeframe
        source_available = bool(candles) or get_latest_candle(
            db,
            trade.symbol,
            entry_timeframe,
        ) is not None
        used_fallback = source_available

    return list(candles), timeframe, used_fallback, source_available


def _candle_checkpoint(candle):
    value = normalize_timestamp_to_utc(
        getattr(candle, "open_time", None)
        or getattr(candle, "candle_time", None)
    )
    if value is None:
        return None
    return value.replace(tzinfo=None)
