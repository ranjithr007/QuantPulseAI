from app.api.v1.signals_api import persist_ready_watchlist_setups_for_stack


def run_watchlist_persist_job():
    return persist_ready_watchlist_setups_for_stack(mode="intraday")
