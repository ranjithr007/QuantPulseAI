from app.regimes.regime_service import run_regime_analysis
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_regime_job(*, context=None):

    print("Running Regime Engine...")

    try:
        return run_regime_analysis(context=context)
    except Exception as ex:
        if not is_transient_network_error(ex):
            print("Regime job error:", summarize_network_error(ex))
        return {
            "status": "FAILED",
            "error": summarize_network_error(ex),
            "source": "regime_job",
        }
