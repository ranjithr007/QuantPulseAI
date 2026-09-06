"""Independent one-second exit protection for both paper books."""
from datetime import datetime, timezone
from types import SimpleNamespace
import time

from app.database.sqlserver import SessionLocal
from app.paper_trading.exit_lock import lock_open_trade
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_shadow_trade_repository import StrategyShadowTradeRepository
from app.repositories.notification_repository import NotificationRepository
from app.services.paper_exit_prices import paper_exit_prices, MAX_PRICE_AGE_SECONDS
from app.utils.freshness import normalize_timestamp_to_utc


_alerted = {}


def _snapshot(trade):
    return SimpleNamespace(**{key: value for key, value in vars(trade).items() if not key.startswith("_")})


def _alert(db, key, message):
    now = time.monotonic()
    if now - _alerted.get(key, float("-inf")) < 300:
        return
    NotificationRepository().create(
        db, event_key=f"fast_exit:{key}:{datetime.now(timezone.utc):%Y%m%d%H%M}",
        category="SYSTEM", event_type="PAPER_EXIT_PROTECTION_DEGRADED", severity="CRITICAL",
        title="Paper exit protection needs attention", message=message, commit=True,
    )
    _alerted[key] = now


def run_paper_trade_fast_exit_job():
    started = time.monotonic()
    paper_exit_prices.start()
    db = SessionLocal()
    summary = {"status": "OK", "processed": 0, "closed": 0, "partial_closes": 0, "stop_moves": 0, "missing_prices": [], "errors": []}
    try:
        books = [(PaperTradeRepository(), False), (StrategyShadowTradeRepository(), True)]
        trades = [(repo, shadow, trade, _snapshot(trade)) for repo, shadow in books for trade in repo.get_open_trades(db)]
        marks = paper_exit_prices.take([snapshot.symbol for _, _, _, snapshot in trades])
        for repo, shadow, trade, snapshot in trades:
            symbol = snapshot.symbol
            quotes = marks.get(symbol, [])
            if not quotes:
                summary["missing_prices"].append(symbol)
                continue
            try:
                processed_before = summary["processed"]
                for mark in quotes:
                    observed = mark["observed_at"]
                    age = (datetime.now(timezone.utc) - observed).total_seconds()
                    opened = normalize_timestamp_to_utc(snapshot.opened_at)
                    if not -1 <= age <= MAX_PRICE_AGE_SECONDS or opened is None or observed < opened:
                        continue
                    price = mark["mark_price"]
                    timestamp = observed.replace(tzinfo=None)
                    candle = SimpleNamespace(high_price=price, low_price=price, close_price=price,
                        candle_time=timestamp, open_time=timestamp, close_time=timestamp,
                        live_mark=True, is_final=False)
                    summary["processed"] += 1
                    # HOLD checks are read-only against this run's snapshot;
                    # only actionable ticks need an additional database lock.
                    if evaluate_paper_trade_exit(snapshot, candle)["action"] == "HOLD":
                        continue
                    # Repository actions commit. Reacquire for every action and
                    # after T1 so another monitor cannot double-close a leg.
                    for _ in range(3):
                        current = lock_open_trade(db, trade)
                        if current is None:
                            break
                        if not -1 <= (datetime.now(timezone.utc) - observed).total_seconds() <= MAX_PRICE_AGE_SECONDS:
                            summary["errors"].append(f"{symbol}: PRICE_EXPIRED_DURING_LOCK")
                            break
                        decision = evaluate_paper_trade_exit(current, candle)
                        action = decision["action"]
                        if action == "CLOSE":
                            repo.close_trade(db, current, decision["exit_price"], decision["result"], fill_profile=decision.get("fill_profile"))
                            summary["closed"] += 1
                        elif action == "PARTIAL_CLOSE":
                            repo.apply_target1(db, current, decision["exit_price"], candle_time=timestamp, evaluated_at=timestamp)
                            snapshot = _snapshot(current)
                            summary["partial_closes"] += 1
                            continue  # Check T2 immediately on the same tick.
                        elif action == "MOVE_STOP":
                            options = {} if shadow else {"notify": False}
                            repo.move_stop_loss(db, current, decision["new_stop_loss"], evaluated_at=timestamp, **options)
                            summary["stop_moves"] += 1
                        snapshot = _snapshot(current)
                        break
                    db.rollback()  # Release read locks; actions already committed.
                    if getattr(snapshot, "status", "OPEN") == "CLOSED":
                        break
                if summary["processed"] == processed_before:
                    # This may be a just-opened trade awaiting its first tick,
                    # or evidence that expired while waiting on the database.
                    summary["missing_prices"].append(symbol)
            except Exception as exc:
                db.rollback()
                summary["errors"].append(f"{symbol}: {type(exc).__name__}")
        summary["duration_seconds"] = round(time.monotonic() - started, 3)
        if summary["duration_seconds"] > 2:
            summary["errors"].append("EXIT_CHECK_EXCEEDED_TWO_SECONDS")
        if summary["missing_prices"] or summary["errors"]:
            summary["status"] = "DEGRADED"
            _alert(db, "unavailable", "One-second paper exit protection is degraded. Missing fresh marks: "
                + ", ".join(sorted(set(summary["missing_prices"])))
                + ". Errors: " + ", ".join(summary["errors"])
                + ". Candle reconciliation remains active; exact stop fills are not guaranteed.")
        return summary
    except Exception as exc:
        db.rollback()
        # Scheduler logs make failures visible even when the database itself
        # is unavailable and cannot persist an alert.
        raise RuntimeError("One-second paper exit protection failed") from exc
    finally:
        db.close()
