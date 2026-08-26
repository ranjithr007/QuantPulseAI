from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.collectors.binances.mark_price_collector import MarkPriceCollector
from app.database.sqlserver import SessionLocal
from app.paper_trading.exit_policy import PAPER_EXIT_MONITOR_TIMEFRAME
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.repositories.candle_repository import get_final_candles_after
from app.repositories.candle_repository import get_latest_candle
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_shadow_trade_repository import (
    StrategyShadowTradeRepository,
)
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
            "status": "OK",
            "processed": 0,
            "policy_updates": 0,
            "closed": 0,
            "partial_closes": 0,
            "stop_moves": 0,
            "wins": 0,
            "losses": 0,
            "still_open": 0,
            "skipped": 0,
            "candles_evaluated": 0,
            "live_marks_evaluated": 0,
            "entry_timeframe_fallbacks": 0,
            "deadline_catchups": 0,
            "overdue_unresolved": 0,
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

                if not candles and _maximum_hold_due(trade):
                    catchup_candle, catchup_error = _deadline_catchup_candle(
                        db,
                        trade,
                        timeframe,
                    )
                    if catchup_candle is not None:
                        candles = [catchup_candle]
                        source_available = True
                        summary["deadline_catchups"] += 1
                    else:
                        summary["overdue_unresolved"] += 1
                        summary["errors"].append(
                            f"{trade.symbol}: {catchup_error or 'OVERDUE_EXIT_PRICE_UNAVAILABLE'}"
                        )

                if not candles:
                    live_mark_candle = _current_mark_candle(trade)
                    if live_mark_candle is not None:
                        candles = [live_mark_candle]
                        source_available = True
                        summary["live_marks_evaluated"] += 1

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

                    if decision["action"] == "MOVE_STOP":
                        updated_trade = repo.move_stop_loss(
                            db,
                            trade,
                            decision["new_stop_loss"],
                            evaluated_at=last_evaluated_at,
                        )
                        summary["stop_moves"] += 1
                        summary["records"].append(
                            {
                                **decision,
                                "paper_trade_id": updated_trade.id,
                                "stop_loss": updated_trade.stop_loss,
                            }
                        )
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
                        if getattr(candle, "live_mark", False):
                            target2_decision = {
                                **evaluate_paper_trade_exit(updated_trade, candle),
                                "monitor_timeframe": timeframe,
                            }
                            if target2_decision["action"] == "CLOSE":
                                closed_trade = repo.close_trade(
                                    db,
                                    updated_trade,
                                    target2_decision["exit_price"],
                                    target2_decision["result"],
                                    fill_profile=target2_decision.get("fill_profile"),
                                )
                                summary["closed"] += 1
                                summary["wins"] += int(closed_trade.result == "WIN")
                                summary["losses"] += int(closed_trade.result != "WIN")
                                summary["records"].append(
                                    {
                                        **target2_decision,
                                        "paper_trade_id": closed_trade.id,
                                        "result": closed_trade.result,
                                        "pnl_percent": closed_trade.pnl_percent,
                                    }
                                )
                                trade_closed = True
                                break
                            if target2_decision["action"] == "MOVE_STOP":
                                updated_trade = repo.move_stop_loss(
                                    db,
                                    updated_trade,
                                    target2_decision["new_stop_loss"],
                                    evaluated_at=last_evaluated_at,
                                )
                                summary["stop_moves"] += 1
                                summary["records"].append(
                                    {
                                        **target2_decision,
                                        "paper_trade_id": updated_trade.id,
                                        "stop_loss": updated_trade.stop_loss,
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
                safe_rollback(db)
                summary["errors"].append(
                    f"{trade.symbol}: {summarize_network_error(ex)}"
                )
                continue

        summary["shadow"] = _run_strategy_shadow_monitor(db)
        if (
            summary["errors"]
            or summary["overdue_unresolved"]
            or summary["shadow"]["errors"]
        ):
            summary["status"] = "FAILED"
        print("Paper Trade Monitor Completed", summary)
        return summary

    except Exception as ex:
        safe_rollback(db)
        summary["status"] = "FAILED"
        summary["errors"].append(summarize_network_error(ex))
        if not is_transient_network_error(ex):
            print("Paper trade monitor job error:", summarize_network_error(ex))
        return summary

    finally:
        db.close()


def _run_strategy_shadow_monitor(db):
    summary = {
        "source": "strategy_shadow_monitor_v1",
        "processed": 0,
        "closed": 0,
        "partial_closes": 0,
        "stop_moves": 0,
        "still_open": 0,
        "errors": [],
        "records": [],
    }
    if not hasattr(db, "get_bind") or not hasattr(db, "query"):
        return summary
    repo = StrategyShadowTradeRepository()
    for trade in repo.get_open_trades(db):
        summary["processed"] += 1
        try:
            candles, timeframe, _used_fallback, source_available = _exit_candles(
                db,
                trade,
            )
            if not candles and _maximum_hold_due(trade):
                catchup, error = _deadline_catchup_candle(db, trade, timeframe)
                if catchup is not None:
                    candles = [catchup]
                    source_available = True
                elif error:
                    summary["errors"].append(f"{trade.strategy_id} {trade.symbol}: {error}")
            if not candles:
                live_mark = _current_mark_candle(trade)
                if live_mark is not None:
                    candles = [live_mark]
                    source_available = True
            if not source_available:
                summary["errors"].append(
                    f"{trade.strategy_id} {trade.symbol}: EXIT_EVIDENCE_UNAVAILABLE"
                )
                continue

            closed = False
            last_checkpoint = None
            for candle in candles:
                decision = evaluate_paper_trade_exit(trade, candle)
                last_checkpoint = _candle_checkpoint(candle)
                action = decision["action"]
                if action == "HOLD":
                    continue
                if action == "MOVE_STOP":
                    repo.move_stop_loss(
                        db,
                        trade,
                        decision["new_stop_loss"],
                        evaluated_at=last_checkpoint,
                    )
                    summary["stop_moves"] += 1
                    continue
                if action == "PARTIAL_CLOSE":
                    trade = repo.apply_target1(
                        db,
                        trade,
                        decision["exit_price"],
                        candle_time=decision.get("candle_time"),
                        evaluated_at=last_checkpoint,
                    )
                    summary["partial_closes"] += 1
                    # A live mark may already be beyond both targets. Recheck
                    # immediately after persisting T1 so the remaining leg exits.
                    if getattr(candle, "live_mark", False):
                        decision = evaluate_paper_trade_exit(trade, candle)
                        if decision["action"] == "CLOSE":
                            trade = repo.close_trade(
                                db,
                                trade,
                                decision["exit_price"],
                                decision["result"],
                                fill_profile=decision.get("fill_profile"),
                            )
                            closed = True
                        elif decision["action"] == "MOVE_STOP":
                            trade = repo.move_stop_loss(
                                db,
                                trade,
                                decision["new_stop_loss"],
                                evaluated_at=last_checkpoint,
                            )
                            summary["stop_moves"] += 1
                    if not closed:
                        continue
                elif action == "CLOSE":
                    trade = repo.close_trade(
                        db,
                        trade,
                        decision["exit_price"],
                        decision["result"],
                        fill_profile=decision.get("fill_profile"),
                    )
                    closed = True

                if closed:
                    summary["closed"] += 1
                    summary["records"].append(
                        {
                            "shadow_trade_id": trade.id,
                            "strategy_id": trade.strategy_id,
                            "symbol": trade.symbol,
                            "result": trade.result,
                            "pnl_percent": trade.pnl_percent,
                        }
                    )
                    break
            if not closed:
                if last_checkpoint is not None:
                    repo.mark_exit_evaluated(db, trade, last_checkpoint)
                summary["still_open"] += 1
        except Exception as exc:
            safe_rollback(db)
            summary["errors"].append(
                f"{trade.strategy_id} {trade.symbol}: {summarize_network_error(exc)}"
            )
    return summary


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
    if getattr(candle, "live_mark", False):
        # A point-in-time mark cannot prove the completed candle's high/low.
        # Keep the durable checkpoint unchanged so the final candle is still
        # replayed later and no intrabar stop/target evidence is skipped.
        return None
    value = normalize_timestamp_to_utc(
        getattr(candle, "open_time", None)
        or getattr(candle, "candle_time", None)
    )
    if value is None:
        return None
    return value.replace(tzinfo=None)


def _current_mark_candle(trade, *, collector=None, now=None):
    mark = (collector or MarkPriceCollector()).get_current_mark_price(trade.symbol)
    if not mark or mark.get("mark_price") is None:
        return None
    observed_at = normalize_timestamp_to_utc(mark.get("observed_at") or now)
    if observed_at is None:
        observed_at = datetime.now(timezone.utc)
    price = float(mark["mark_price"])
    timestamp = observed_at.replace(tzinfo=None)
    return SimpleNamespace(
        high_price=price,
        low_price=price,
        close_price=price,
        candle_time=timestamp,
        open_time=timestamp,
        close_time=timestamp,
        is_final=False,
        live_mark=True,
        mark_source=mark.get("source") or "CURRENT_MARK_PRICE",
    )


def _maximum_hold_due(trade, now=None):
    opened_at = normalize_timestamp_to_utc(getattr(trade, "opened_at", None))
    max_hold_hours = getattr(trade, "max_hold_hours", None)
    if opened_at is None or not max_hold_hours:
        return False
    observed_at = normalize_timestamp_to_utc(now or datetime.now(timezone.utc))
    return observed_at >= opened_at + timedelta(hours=float(max_hold_hours))


def _deadline_catchup_candle(db, trade, timeframe, *, collector=None, now=None):
    deadline = _maximum_hold_deadline(trade)
    if deadline is None:
        return None, "MAX_HOLD_DEADLINE_UNAVAILABLE"

    latest = get_latest_candle(db, trade.symbol, timeframe)
    latest_close = normalize_timestamp_to_utc(
        getattr(latest, "close_time", None) if latest is not None else None
    )
    if latest is not None and latest_close is not None and latest_close >= deadline:
        latest.force_time_exit = True
        latest.deadline_catchup_source = "LATEST_FINAL_DB_CANDLE"
        return latest, None

    mark = (collector or MarkPriceCollector()).get_current_mark_price(trade.symbol)
    if not mark:
        return None, "OVERDUE_EXIT_MARK_PRICE_UNAVAILABLE"
    observed_at = normalize_timestamp_to_utc(mark.get("observed_at") or now)
    if observed_at is None or observed_at < deadline:
        return None, "OVERDUE_EXIT_MARK_PRICE_PREDATES_DEADLINE"

    price = float(mark["mark_price"])
    timestamp = observed_at.replace(tzinfo=None)
    return SimpleNamespace(
        high_price=price,
        low_price=price,
        close_price=price,
        candle_time=timestamp,
        open_time=timestamp,
        close_time=timestamp,
        is_final=True,
        force_time_exit=True,
        deadline_catchup_source=mark.get("source") or "CURRENT_MARK_PRICE",
    ), None


def _maximum_hold_deadline(trade):
    opened_at = normalize_timestamp_to_utc(getattr(trade, "opened_at", None))
    max_hold_hours = getattr(trade, "max_hold_hours", None)
    if opened_at is None or not max_hold_hours:
        return None
    return opened_at + timedelta(hours=float(max_hold_hours))
