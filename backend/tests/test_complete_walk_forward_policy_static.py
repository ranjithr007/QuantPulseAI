from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_complete_walk_forward_runner_uses_deployed_paper_risk_policy():
    source = (
        PROJECT_ROOT
        / "backend"
        / "scripts"
        / "run_complete_walk_forward_validation.py"
    ).read_text(encoding="utf-8")

    assert 'exit_distance_model="PAPER_POLICY"' in source
    assert "stop_grid=(PRODUCTION_STOP_PERCENT,)" in source
    assert "target_grid=(PRODUCTION_TARGET_PERCENT,)" in source
    assert "risk_percent_per_trade=PRODUCTION_MAX_RISK_PERCENT" in source
    assert "PRODUCTION_MAX_RISK_PERCENT = 1.0" in source


def test_complete_walk_forward_scope_remains_all_current_timeframes_and_sides():
    source = (
        PROJECT_ROOT
        / "backend"
        / "scripts"
        / "run_complete_walk_forward_validation.py"
    ).read_text(encoding="utf-8")

    assert "DEFAULT_TIMEFRAMES = tuple(OFFICIAL_ENTRY_TIMEFRAMES)" in source
    assert 'DEFAULT_SIGNALS = ("LONG", "SHORT")' in source
    assert "side_run_count" in source
