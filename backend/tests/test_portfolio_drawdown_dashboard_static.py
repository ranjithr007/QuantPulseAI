from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pnl_dashboard_exposes_new_entry_drawdown_pause():
    source = (
        ROOT
        / "frontend"
        / "quantpulse-dashboard"
        / "src"
        / "components"
        / "PnLSection.jsx"
    ).read_text(encoding="utf-8")

    assert "paperWallet?.entry_protection?.new_entries_paused" in source
    assert "New official paper entries paused" in source
    assert "Existing positions remain under normal exit monitoring" in source


def test_pnl_dashboard_exposes_fast_exit_protection_pause():
    source = (
        ROOT
        / "frontend"
        / "quantpulse-dashboard"
        / "src"
        / "components"
        / "PnLSection.jsx"
    ).read_text(encoding="utf-8")

    assert "paperWallet?.exit_protection?.ready === false" in source
    assert "New entries blocked: exit protection unavailable" in source
    assert "Existing positions remain monitored when the worker recovers" in source
