from app.backtesting.combined_timeframe_replay import (
    build_combined_timeframe_portfolio_replay,
)


def _trade(entry, exit_, confidence, pnl, *, side="LONG"):
    minimum_tier = confidence < 60
    return {
        "side": side,
        "entry_time": entry,
        "exit_time": exit_,
        "confidence": confidence,
        "pnl": pnl,
        "pnl_percent": pnl / 100,
        "fees": 2,
        "sizing": {
            "notional": 2_000,
            "position_tier": "MINIMUM" if minimum_tier else "MAXIMUM",
            "risk_percent": 0.5 if minimum_tier else 1.0,
        },
        "timeframe_stack": {
            "decision_chain": {
                "signal": {"confidence": confidence, "score": confidence},
                "risk": {"confidence": confidence, "risk_reward": 2.0},
            }
        },
    }


def test_combined_replay_selects_strongest_and_waits_for_coin_exit():
    scopes = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "signal": "LONG",
            "trades": [
                _trade(
                    "2026-01-01T01:00:00+00:00",
                    "2026-01-01T04:00:00+00:00",
                    50,
                    100,
                ),
                _trade(
                    "2026-01-01T05:00:00+00:00",
                    "2026-01-01T06:00:00+00:00",
                    55,
                    100,
                ),
            ],
        },
        {
            "symbol": "BTCUSDT",
            "timeframe": "4h",
            "signal": "SHORT",
            "trades": [
                _trade(
                    "2026-01-01T01:00:00+00:00",
                    "2026-01-01T03:00:00+00:00",
                    80,
                    200,
                    side="SHORT",
                ),
                _trade(
                    "2026-01-01T02:00:00+00:00",
                    "2026-01-01T03:00:00+00:00",
                    90,
                    200,
                    side="SHORT",
                ),
            ],
        },
    ]

    result = build_combined_timeframe_portfolio_replay(scopes)
    btc = result["per_symbol"]["BTCUSDT"]

    assert result["status"] == "PASS"
    assert [trade["entry_timeframe"] for trade in btc["trades"]] == ["4h", "1h"]
    assert [trade["entry_time"] for trade in btc["trades"]] == [
        "2026-01-01T01:00:00+00:00",
        "2026-01-01T05:00:00+00:00",
    ]
    assert btc["rejection_counts"] == {"SYMBOL_ACTIVE_POSITION": 2}
    assert btc["overlap_audit"] == {
        "status": "PASS",
        "violation_count": 0,
        "violations": [],
    }
    assert result["portfolio"]["strongest_selection_audit"] == {
        "status": "PASS",
        "contested_entry_count": 1,
        "violation_count": 0,
        "violations": [],
    }
    assert result["confidence_tier_audit"] == {
        "status": "PASS",
        "candidate_count": 4,
        "minimum_tier_count": 2,
        "maximum_tier_count": 2,
        "below_entry_floor_count": 0,
        "violation_count": 0,
        "violations": [],
    }


def test_combined_replay_allows_other_coins_while_btc_is_active():
    scopes = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "signal": "LONG",
            "trades": [
                _trade(
                    "2026-01-01T01:00:00+00:00",
                    "2026-01-01T04:00:00+00:00",
                    70,
                    100,
                )
            ],
        },
        {
            "symbol": "ETHUSDT",
            "timeframe": "2h",
            "signal": "SHORT",
            "trades": [
                _trade(
                    "2026-01-01T02:00:00+00:00",
                    "2026-01-01T03:00:00+00:00",
                    65,
                    100,
                    side="SHORT",
                )
            ],
        },
    ]

    result = build_combined_timeframe_portfolio_replay(scopes)

    assert result["portfolio"]["total_trades"] == 2
    assert {trade["symbol"] for trade in result["portfolio"]["trades"]} == {
        "BTCUSDT",
        "ETHUSDT",
    }
    assert result["portfolio"]["overlap_audit"]["violation_count"] == 0
