from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.paper_trading.reentry_policy import same_side_stop_reentry_cooldown


NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _closed_trade(*, side="LONG", reason="STOP", minutes_ago=10, trade_id=1):
    return SimpleNamespace(
        id=trade_id,
        symbol="BTCUSDT",
        side=side,
        status="CLOSED",
        exit_reason=reason,
        closed_at=NOW - timedelta(minutes=minutes_ago),
    )


def test_same_direction_is_blocked_for_30_minutes_after_stop():
    cooldown = same_side_stop_reentry_cooldown(
        [_closed_trade()],
        "BTCUSDT",
        "LONG",
        now=NOW,
    )

    assert cooldown["active"] is True
    assert cooldown["blocked_side"] == "LONG"
    assert cooldown["remaining_seconds"] == 20 * 60
    assert cooldown["stopped_trade_id"] == 1


def test_opposite_direction_can_enter_during_same_coin_cooldown():
    cooldown = same_side_stop_reentry_cooldown(
        [_closed_trade(side="LONG")],
        "BTCUSDT",
        "SHORT",
        now=NOW,
    )

    assert cooldown["active"] is False


def test_same_direction_can_enter_at_exact_cooldown_boundary():
    cooldown = same_side_stop_reentry_cooldown(
        [_closed_trade(minutes_ago=30)],
        "BTCUSDT",
        "LONG",
        now=NOW,
    )

    assert cooldown["active"] is False
    assert cooldown["remaining_seconds"] == 0


def test_target_exit_does_not_start_stop_reentry_cooldown():
    cooldown = same_side_stop_reentry_cooldown(
        [_closed_trade(reason="TARGET2")],
        "BTCUSDT",
        "LONG",
        now=NOW,
    )

    assert cooldown["active"] is False


def test_open_trade_is_not_treated_as_post_stop_cooldown():
    trade = _closed_trade()
    trade.status = "OPEN"

    cooldown = same_side_stop_reentry_cooldown(
        [trade],
        "BTCUSDT",
        "LONG",
        now=NOW,
    )

    assert cooldown["active"] is False
