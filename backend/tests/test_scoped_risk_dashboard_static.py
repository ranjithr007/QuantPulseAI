from pathlib import Path

from app.api.v1 import risk_api


ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_daily_loss_fallback_uses_account_snapshot_not_lifetime_pnl():
    source = (
        ROOT
        / "frontend"
        / "quantpulse-dashboard"
        / "src"
        / "hooks"
        / "dashboardTransforms.js"
    ).read_text(encoding="utf-8")

    assert "accountRisk?.limit_reached === true" in source
    assert "performance?.total_pnl_percent" not in source
    assert "Active trade already exists for this coin" in source
    assert "blockerScopes" in source


def test_auto_trading_page_displays_three_blocker_scopes():
    source = (
        ROOT
        / "frontend"
        / "quantpulse-dashboard"
        / "src"
        / "pages"
        / "AutoTradingPage.jsx"
    ).read_text(encoding="utf-8")

    assert 'label: "Trade-level"' in source
    assert 'label: "Coin-level"' in source
    assert 'label: "Account-level"' in source


def test_computed_risk_is_scoped_to_the_requested_timeframe_and_mode(monkeypatch):
    monkeypatch.setattr(
        risk_api.risk_engine,
        "analyze_trade_plan",
        lambda **_kwargs: {
            "symbol": "ETHUSDT",
            "signal": "BUY",
            "decision": "APPROVE",
            "entry": 100.0,
            "stop_loss": 99.25,
            "targets": {"t1": 101.5, "t2": 102.3},
            "risk_reward": 2.0,
            "position_size": 1.0,
            "risk_percent": 0.5,
            "confidence": 60.0,
        },
    )

    result = risk_api._build_computed_risk(
        {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "signal": "BUY",
            "current_price": 100.0,
            "confidence": 60.0,
            "trade_plan": {
                "entry": 100.0,
                "stop_loss": 99.25,
                "target1": 101.5,
                "target2": 102.3,
                "atr": 1.0,
            },
        },
        0.5,
        3900,
        timeframe="4h",
        mode="intraday",
    )

    assert result["timeframe"] == "4h"
    assert result["mode"] == "intraday"
