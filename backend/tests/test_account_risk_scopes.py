from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace

from app.risk.account_risk import build_account_daily_pnl_snapshot


def _trade(
    symbol,
    *,
    status="OPEN",
    side="LONG",
    entry=100.0,
    stop=95.0,
    risk_percent=0.5,
    pnl_percent=None,
    closed_at=None,
):
    return SimpleNamespace(
        id=symbol,
        symbol=symbol,
        status=status,
        side=side,
        entry_price=entry,
        stop_loss=stop,
        risk_percent=risk_percent,
        fee_bps=0,
        pnl_percent=pnl_percent,
        exit_price=None,
        closed_at=closed_at,
    )


def test_single_coin_price_loss_is_scaled_to_account_risk():
    snapshot = build_account_daily_pnl_snapshot(
        [_trade("BTCUSDT")],
        {"BTCUSDT": 96.0},
        daily_loss_limit=4.0,
    )

    assert snapshot["daily_pnl_percent"] == -0.4
    assert snapshot["limit_reached"] is False
    assert snapshot["contributions"][0]["market_pnl_percent"] == -4.0
    assert snapshot["contributions"][0]["account_exposure_factor"] == 0.1


def test_each_open_trade_uses_its_own_symbol_price():
    snapshot = build_account_daily_pnl_snapshot(
        [
            _trade("BTCUSDT", entry=100.0, stop=95.0),
            _trade("XRPUSDT", entry=1.0, stop=0.95),
        ],
        {"BTCUSDT": 96.0, "XRPUSDT": 0.98},
        daily_loss_limit=4.0,
    )

    by_symbol = {item["symbol"]: item for item in snapshot["contributions"]}
    assert by_symbol["BTCUSDT"]["market_pnl_percent"] == -4.0
    assert by_symbol["XRPUSDT"]["market_pnl_percent"] == -2.0
    assert snapshot["daily_pnl_percent"] == -0.6
    assert snapshot["limit_reached"] is False


def test_combined_account_loss_blocks_only_at_configured_threshold():
    now = datetime.utcnow()
    trades = [
        _trade(
            "BTCUSDT",
            status="CLOSED",
            risk_percent=1.0,
            pnl_percent=-10.0,
            closed_at=now - timedelta(hours=2),
        ),
        _trade(
            "ETHUSDT",
            status="CLOSED",
            risk_percent=1.0,
            pnl_percent=-10.0,
            closed_at=now - timedelta(hours=3),
        ),
    ]

    snapshot = build_account_daily_pnl_snapshot(
        trades,
        daily_loss_limit=4.0,
        as_of=now,
    )

    assert snapshot["daily_pnl_percent"] == -4.0
    assert snapshot["limit_reached"] is True


def test_closed_loss_outside_daily_window_does_not_block_account():
    now = datetime.utcnow()
    snapshot = build_account_daily_pnl_snapshot(
        [
            _trade(
                "BTCUSDT",
                status="CLOSED",
                risk_percent=1.0,
                pnl_percent=-20.0,
                closed_at=now - timedelta(hours=25),
            )
        ],
        daily_loss_limit=4.0,
        as_of=now,
    )

    assert snapshot["daily_pnl_percent"] == 0
    assert snapshot["limit_reached"] is False


def test_required_open_mark_price_fails_closed_without_entry_price_fallback():
    snapshot = build_account_daily_pnl_snapshot(
        [_trade("BTCUSDT")],
        {},
        require_open_prices=True,
    )

    assert snapshot["risk_available"] is False
    assert snapshot["daily_pnl_percent"] == 0
    assert snapshot["contributions"] == []
    assert "Fresh mark price" in snapshot["skipped"][0]["reason"]


def test_persisted_notional_and_remaining_fraction_drive_account_exposure():
    trade = _trade("BTCUSDT")
    trade.confidence = 90
    trade.position_notional_inr = 75_000
    trade.remaining_position_fraction = 0.5

    snapshot = build_account_daily_pnl_snapshot(
        [trade],
        {"BTCUSDT": 96},
        require_open_prices=True,
    )

    assert snapshot["risk_available"] is True
    assert snapshot["contributions"][0]["account_exposure_factor"] == 0.375
    assert snapshot["daily_pnl_percent"] == -1.5


def test_closed_trade_uses_persisted_realized_inr_for_exact_account_pnl():
    trade = _trade(
        "BTCUSDT",
        status="CLOSED",
        pnl_percent=-4.0,
        closed_at=datetime.utcnow() - timedelta(hours=1),
    )
    trade.position_notional_inr = 75_000
    trade.remaining_position_fraction = 0.5
    trade.realized_pnl_inr = -3_000

    snapshot = build_account_daily_pnl_snapshot([trade])

    assert snapshot["daily_pnl_percent"] == -3.0
    assert snapshot["contributions"][0]["account_pnl_source"] == (
        "PERSISTED_REALIZED_INR"
    )
