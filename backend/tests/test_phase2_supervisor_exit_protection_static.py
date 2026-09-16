from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_supervisor_reports_fast_exit_protection_state_changes():
    source = (
        ROOT / "scripts" / "phase2_supervisor.ps1"
    ).read_text(encoding="utf-8")

    assert "exit_protection_ready = $exitProtectionReady" in source
    assert 'Invoke-Api "/health/exit-protection" -TimeoutSeconds 3' in source
    assert "exit_protection_reason = $exitProtection.reason" in source
    assert "Paper execution blocked by exit protection" in source
    assert "Paper exit protection is ready" in source
