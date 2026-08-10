from app.contracts.control import AutomationEnvelope
from app.contracts.control import LiveMarketResponse
from app.contracts.control import MarketRefreshResponse
from app.contracts.control import PaperTradeExecutionResponse


def test_control_contracts_cover_success_and_fallback_states():
    automation = AutomationEnvelope(
        source="automation_settings",
        changed=True,
        settings={"enabled": False},
    )
    live = LiveMarketResponse(
        source="live_market_cache",
        status="CONNECTING",
        available=True,
        records=[],
    )
    execution = PaperTradeExecutionResponse(
        source="paper_trade_execution_simulator_fallback",
        database_status="UNAVAILABLE",
        message="database unavailable",
    )
    refresh = MarketRefreshResponse(
        source="binance_futures_refresh",
        symbol="DOGEUSDT",
        timeframe="1h",
        saved_count=1,
    )

    assert automation.changed is True
    assert live.status == "CONNECTING"
    assert execution.executed_count == 0
    assert refresh.saved_count == 1
