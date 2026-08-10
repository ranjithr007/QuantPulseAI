from app.contracts.bundle import IntelligenceBundleResponse
from app.contracts.bundle import PaperTradeBundleResponse
from app.contracts.bundle import RiskBundleResponse


def test_bundle_contracts_accept_success_and_failure_envelopes():
    intelligence = IntelligenceBundleResponse(
        symbol="DOGEUSDT",
        timeframe="1h",
        stale_after_seconds=900,
        source="intelligence_bundle",
        bundleStatus="PARTIAL",
        failures=[{"section": "smc", "error": "unavailable"}],
    )
    paper = PaperTradeBundleResponse(
        source="paper_trade_bundle_fallback",
        symbol_filter="DOGEUSDT",
        database_status="UNAVAILABLE",
        message="database unavailable",
        openTrades={"count": 0, "records": []},
        closedTrades={"count": 0, "records": []},
    )
    risk = RiskBundleResponse(
        symbol="DOGEUSDT",
        timeframe="1h",
        stale_after_seconds=900,
        source="risk_bundle",
        status="FAILED",
        data_scope="timeframe",
        error="risk unavailable",
    )

    assert intelligence.failures[0].section == "smc"
    assert paper.database_status == "UNAVAILABLE"
    assert risk.status == "FAILED"
