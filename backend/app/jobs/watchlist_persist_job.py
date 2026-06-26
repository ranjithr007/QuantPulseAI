from app.api.v1.signals_api import persist_ready_watchlist_setups_for_stack
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_watchlist_persist_job():
    try:
        return persist_ready_watchlist_setups_for_stack(mode="intraday")
    except Exception as ex:
        if not is_transient_network_error(ex):
            print("Watchlist persist job error:", summarize_network_error(ex))
        return {
            "status": "FAILED",
            "error": summarize_network_error(ex),
            "source": "watchlist_persist",
        }
