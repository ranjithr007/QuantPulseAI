from app.api.v1.signals_api import persist_ready_watchlist_setups_for_stack
from app.risk.risk_engine import RiskEngine
from app.repositories.trade_plan_repository import TradePlanRepository
from app.database.sqlserver import SessionLocal
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error

MIN_READY_CONFIDENCE = RiskEngine.MIN_CONFIDENCE


def run_watchlist_persist_job():
    try:
        cleanup_result = _invalidate_low_confidence_open_trades()
        persist_result = persist_ready_watchlist_setups_for_stack(mode="intraday")
        return {
            "status": _persistence_status(persist_result),
            "source": "watchlist_persist",
            "cleanup": cleanup_result,
            "persistence": persist_result,
        }
    except Exception as ex:
        if not is_transient_network_error(ex):
            print("Watchlist persist job error:", summarize_network_error(ex))
        return {
            "status": "FAILED",
            "error": summarize_network_error(ex),
            "source": "watchlist_persist",
        }


def _persistence_status(result):
    """Do not turn a returned persistence failure into a successful worker run.

    Ordinary candidate WAIT/skips are not infrastructure failures. The current
    writer returns a summary without a status on success, which remains valid.
    """
    if not isinstance(result, dict):
        return "FAILED"
    status = str(result.get("status") or "").upper()
    if status in {"FAILED", "ERROR", "UNAVAILABLE", "BLOCKED"}:
        return status
    cache = result.get("cache") or {}
    if (status in {"PARTIAL", "DEGRADED"}
            or result.get("error") or result.get("errors")
            or result.get("failed_symbols")
            or cache.get("stale_symbols") or cache.get("missing_symbols")):
        return "DEGRADED"
    return "OK"


def _invalidate_low_confidence_open_trades():
    db = SessionLocal()

    try:
        repo = TradePlanRepository()
        invalidated = repo.invalidate_open_trades_below_confidence(
            db,
            MIN_READY_CONFIDENCE,
        )
        return {
            "threshold": MIN_READY_CONFIDENCE,
            "invalidated_count": len(invalidated),
            "invalidated": [
                {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "confidence": trade.confidence,
                    "result": trade.result,
                }
                for trade in invalidated
            ],
        }
    finally:
        db.close()
