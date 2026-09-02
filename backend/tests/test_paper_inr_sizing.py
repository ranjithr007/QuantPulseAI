import pytest

from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.paper_trading.inr_sizing import build_inr_paper_wallet
from app.paper_trading.inr_sizing import fit_inr_paper_sizing_to_margin_capacity


def test_minimum_confidence_tier_uses_75_percent_inr_notional():
    sizing = build_inr_paper_sizing(49, leverage=5, fee_bps=7.5)

    assert sizing["currency"] == "INR"
    assert sizing["margin_type"] == "INR-M"
    assert sizing["paper_capital_inr"] == 200_000
    assert sizing["position_tier"] == "MINIMUM"
    assert sizing["allocation_percent"] == 75
    assert sizing["position_notional_inr"] == 150_000
    assert sizing["margin_used_inr"] == 30_000
    assert sizing["estimated_max_loss_inr"] == 1_350


def test_full_confidence_tier_uses_85_percent_inr_notional():
    sizing = build_inr_paper_sizing(60, leverage=5, fee_bps=7.5)

    assert sizing["position_tier"] == "MAXIMUM"
    assert sizing["allocation_percent"] == 85
    assert sizing["position_notional_inr"] == 170_000
    assert sizing["margin_used_inr"] == 34_000
    assert sizing["estimated_max_loss_inr"] == 1_530


def test_new_position_scales_to_remaining_account_margin_capacity():
    requested = build_inr_paper_sizing(49, leverage=5, fee_bps=7.5)

    sizing = fit_inr_paper_sizing_to_margin_capacity(requested, 22_000)

    assert sizing["capacity_adjusted"] is True
    assert sizing["position_tier"] == "CAPACITY_ADJUSTED"
    assert sizing["requested_position_tier"] == "MINIMUM"
    assert sizing["requested_margin_inr"] == 30_000
    assert sizing["margin_used_inr"] == 22_000
    assert sizing["position_notional_inr"] == 110_000
    assert sizing["allocation_percent"] == 55
    assert sizing["estimated_max_loss_inr"] == 990
    assert sizing["estimated_max_loss_percent"] == 0.495


def test_margin_capacity_fit_never_expands_requested_position():
    requested = build_inr_paper_sizing(60, leverage=5, fee_bps=7.5)

    sizing = fit_inr_paper_sizing_to_margin_capacity(requested, 50_000)

    assert sizing["capacity_adjusted"] is False
    assert sizing["position_tier"] == "MAXIMUM"
    assert sizing["margin_used_inr"] == 34_000


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

    assert wallet["paper_capital_inr"] == 200_000
    assert wallet["committed_margin_inr"] == 47_000
    assert wallet["available_margin_inr"] == 153_000
    assert wallet["remaining_margin_capacity_inr"] == 123_000
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

    assert wallet["committed_margin_inr"] == 136_000
    assert wallet["available_margin_inr"] == 64_000
    assert wallet["margin_utilization_percent"] == 68
    assert wallet["remaining_margin_capacity_inr"] == 34_000


def test_wallet_balance_comes_from_persisted_ledger_deltas():
    trades = [
        {
            "id": 1,
            "symbol": "BTCUSDT",
            "status": "OPEN",
            "confidence": 90,
            "position_notional_inr": 75_000,
            "margin_used_inr": 15_000,
            "leverage": 5,
            "allocation_percent": 75,
            "remaining_position_fraction": 1.0,
        }
    ]
    ledger = [
        {"delta_inr": 500, "event_type": "TARGET1_REALIZED"},
        {"delta_inr": -100, "event_type": "FINAL_CLOSE_REALIZED"},
    ]

    wallet = build_inr_paper_wallet(trades, ledger_entries=ledger)

    assert wallet["accounting_source"] == "PERSISTED_LEDGER"
    assert wallet["realized_pnl_inr"] == 400
    assert wallet["wallet_balance_inr"] == 200_400
    assert wallet["committed_margin_inr"] == 15_000
    assert wallet["available_margin_inr"] == 185_400
    assert wallet["positions"][0]["notional_inr"] == 75_000


def test_wallet_accepts_exact_trade_aggregate_with_bounded_history():
    wallet = build_inr_paper_wallet(
        [
            {
                "id": 1,
                "symbol": "BTCUSDT",
                "side": "LONG",
                "status": "OPEN",
                "entry_price": 100,
                "position_notional_inr": 75_000,
                "margin_used_inr": 15_000,
                "remaining_position_fraction": 1.0,
            }
        ],
        trade_realized_pnl_inr=1_250.5,
    )

    assert wallet["accounting_source"] == "PERSISTED_TRADE_AGGREGATE"
    assert wallet["realized_pnl_inr"] == 1_250.5
    assert wallet["wallet_balance_inr"] == 201_250.5
    assert wallet["open_position_count"] == 1


def test_wallet_equity_includes_open_unrealized_pnl_from_mark_prices():
    trades = [
        {
            "id": 1,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "status": "OPEN",
            "entry_price": 100,
            "fee_bps": 7.5,
            "position_notional_inr": 75_000,
            "margin_used_inr": 15_000,
            "remaining_position_fraction": 1.0,
        }
    ]

    wallet = build_inr_paper_wallet(
        trades,
        current_prices={"BTCUSDT": 99},
        require_open_prices=True,
    )

    assert wallet["valuation_complete"] is True
    assert wallet["unrealized_pnl_inr"] == -862.5
    assert wallet["equity_inr"] == 199_137.5
    assert wallet["available_margin_inr"] == 184_137.5
    assert wallet["positions"][0]["unrealized_pnl_inr"] == -862.5


def test_wallet_marks_open_valuation_incomplete_without_required_price():
    wallet = build_inr_paper_wallet(
        [
            {
                "id": 1,
                "symbol": "XRPUSDT",
                "side": "SHORT",
                "status": "OPEN",
                "entry_price": 1.0,
                "confidence": 49,
            }
        ],
        require_open_prices=True,
    )

    assert wallet["valuation_complete"] is False
    assert wallet["missing_price_symbols"] == ["XRPUSDT"]


@pytest.mark.parametrize("leverage", [0, -1])
def test_invalid_paper_leverage_is_rejected(leverage):
    with pytest.raises(ValueError, match="at least 1"):
        build_inr_paper_sizing(60, leverage=leverage)
