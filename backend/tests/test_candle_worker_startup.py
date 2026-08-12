from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_candle_worker_is_restricted_to_collection_and_completeness():
    source = (BACKEND_ROOT / "start_candle_worker.ps1").read_text(
        encoding="utf-8"
    )

    assert '$env:QUANTPULSE_SCHEDULER_JOBS = "market,candle_completeness"' in source
    assert '$env:QUANTPULSE_START_LIVE_MARKET = "false"' in source
    assert "deterministic_pipeline" not in source
    assert "paper_trade" not in source
    assert "-WindowStyle Hidden" in source


def test_candle_worker_prevents_duplicate_app_worker_processes():
    source = (BACKEND_ROOT / "start_candle_worker.ps1").read_text(
        encoding="utf-8"
    )

    assert '$_ .CommandLine' not in source
    assert '$_.CommandLine -like "*app.worker*"' in source
    assert "A QuantPulse worker is already running" in source

