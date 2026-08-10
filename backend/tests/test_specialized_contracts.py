from app.contracts.specialized import DerivativesResponse
from app.contracts.specialized import MarketCandlesResponse
from app.contracts.specialized import SymbolContextResponse


def test_specialized_contracts_accept_live_and_empty_states():
    signal = SymbolContextResponse(
        symbol="DOGEUSDT",
        timeframe="1h",
        source="entry_trigger",
        status="WAIT",
        trigger={"ready": False},
    )
    market = MarketCandlesResponse(
        symbol="DOGEUSDT",
        timeframe="1h",
        source="canonical_market_candles",
        candles=[],
    )
    derivatives = DerivativesResponse(
        symbol="DOGEUSDT",
        source="derivatives",
        status="OK",
        data_scope="symbol",
        availability={"funding": False, "open_interest": False},
    )

    assert signal.trigger["ready"] is False
    assert market.candles == []
    assert derivatives.symbol == "DOGEUSDT"
