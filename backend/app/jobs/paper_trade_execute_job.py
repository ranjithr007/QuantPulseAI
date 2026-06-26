from app.api.v1.paper_trade_api import execute_paper_trade_candidates_for_symbol
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_paper_trade_execute_job():
    try:
        return execute_paper_trade_candidates_for_symbol()
    except Exception as ex:
        if not is_transient_network_error(ex):
            print("Paper trade execute job error:", summarize_network_error(ex))
        return {
            "status": "FAILED",
            "error": summarize_network_error(ex),
            "source": "paper_trade_execute",
        }
