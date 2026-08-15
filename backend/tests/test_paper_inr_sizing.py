import pytest

from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.paper_trading.inr_sizing import build_inr_paper_wallet


def test_minimum_confidence_tier_uses_75_percent_inr_notional():
    sizing = build_inr_paper_sizing(49, leverage=5, fee_bps=7.5)

    assert sizing["currency"] == "INR"
    assert sizing["margin_type"] == "INR-M"
    assert sizing["paper_capital_inr"] == 100_000
    assert sizing["position_tier"] == "MINIMUM"
    assert sizing["allocation_percent"] == 75
    assert sizing["position_notional_inr"] == 75_000
    assert sizing["margin_used_inr"] == 15_000
    assert sizing["estimated_max_loss_inr"] == 675


def test_full_confidence_tier_uses_85_percent_inr_notional():
    sizing = build_inr_paper_sizing(60, leverage=5, fee_bps=7.5)

    assert sizing["position_tier"] == "MAXIMUM"
    assert sizing["allocation_percent"] == 85
    assert sizing["position_notional_inr"] == 85_000
    assert sizing["margin_used_inr"] == 17_000
    assert sizing["estimated_max_loss_inr"] == 765


def test_wallet_tracks_remaining_margin_after_target_one_partial_exit():
    trades = [
        {
            "id": 1,
            "symbol": "BTCUSDT",
            "status": "OPEN",
            "confidence": 65,
            "fee_bps": 7.5,
            "remaining_position_fraction": 0.5,
        },
        {
            "id": 2,
            "symbol": "XRPUSDT",
            "status": "OPEN",
            "confidence": 49,
            "fee_bps": 7.5,
            "remaining_position_fraction": 1.0,
        },
    ]

    wallet = build_inr_paper_wallet(trades)

    assert wallet["paper_capital_inr"] == 100_000
    assert wallet["committed_margin_inr"] == 23_500
    assert wallet["available_margin_inr"] == 76_500
    assert wallet["remaining_margin_capacity_inr"] == 61_500
    assert wallet["margin_utilization_percent"] == 23.5


def test_four_full_size_positions_keep_32_percent_wallet_reserve():
    trades = [
        {
            "id": index,
            "symbol": f"COIN{index}USDT",
            "status": "OPEN",
            "confidence": 60,
            "remaining_position_fraction": 1.0,
        }
        for index in range(1, 5)
    ]

    wallet = build_inr_paper_wallet(trades)

    assert wallet["committed_margin_inr"] == 68_000
    assert wallet["available_margin_inr"] == 32_000
    assert wallet["margin_utilization_percent"] == 68
    assert wallet["remaining_margin_capacity_inr"] == 17_000


@pytest.mark.parametrize("leverage", [0, -1])
def test_invalid_paper_leverage_is_rejected(leverage):
    with pytest.raises(ValueError, match="at least 1"):
        build_inr_paper_sizing(60, leverage=leverage)
