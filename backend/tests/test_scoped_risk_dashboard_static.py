from pathlib import Path


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
