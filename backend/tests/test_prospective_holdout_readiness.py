import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backtesting.prospective_holdout_readiness import assess_data_readiness
from app.backtesting.prospective_holdout_readiness import collect_inventory


CUTOFF = datetime(2026, 8, 23, 16, tzinfo=timezone.utc)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _row(
    *,
    dataset="futures_candles",
    records=24,
    latest_time=None,
    cadence_minutes=60,
    freshness_minutes=120,
    critical=True,
    event_driven=False,
):
    return {
        "dataset": dataset,
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "records": records,
        "first_time": CUTOFF + timedelta(hours=1),
        "latest_time": latest_time or CUTOFF + timedelta(days=1),
        "cadence_minutes": cadence_minutes,
        "freshness_minutes": freshness_minutes,
        "critical": critical,
        "event_driven": event_driven,
    }


def test_healthy_early_inventory_remains_collecting_without_outcome_access():
    observed = CUTOFF + timedelta(days=1)
    report = assess_data_readiness([_row()], cutoff=CUTOFF, observed_at=observed)

    assert report["status"] == "COLLECTING_DATA"
    assert report["days_remaining"] == 6
    assert report["scopes"][0]["status"] == "HEALTHY"
    assert report["outcome_data_accessed"] is False
    assert report["signals_constructed"] is False
    assert report["trades_constructed"] is False


def test_missing_or_stale_critical_data_fails_readiness():
    observed = CUTOFF + timedelta(days=2)
    report = assess_data_readiness(
        [_row(records=20, latest_time=CUTOFF + timedelta(hours=12))],
        cutoff=CUTOFF,
        observed_at=observed,
    )

    scope = report["scopes"][0]
    assert report["status"] == "DATA_GAPS"
    assert report["critical_gap_count"] == 1
    assert scope["coverage_percent"] < 90
    assert scope["status"] == "GAP"


def test_event_driven_zero_rows_is_visible_but_not_a_false_failure():
    observed = CUTOFF + timedelta(days=1)
    rows = [
        _row(),
        _row(
            dataset="liquidations",
            records=0,
            latest_time=None,
            cadence_minutes=None,
            freshness_minutes=None,
            critical=False,
            event_driven=True,
        ),
    ]
    rows[1]["latest_time"] = None
    report = assess_data_readiness(rows, cutoff=CUTOFF, observed_at=observed)

    liquidation = report["scopes"][1]
    assert liquidation["status"] == "NO_EVENTS_OBSERVED"
    assert report["critical_gap_count"] == 0
    assert report["status"] == "COLLECTING_DATA"


def test_complete_critical_inventory_opens_data_validation_window_after_day_seven():
    observed = CUTOFF + timedelta(days=8)
    row = _row(
        records=192,
        latest_time=observed,
    )
    report = assess_data_readiness([row], cutoff=CUTOFF, observed_at=observed)

    assert report["status"] == "DATA_READY_FOR_WALK_FORWARD"
    assert report["validation_window_open"] is True
    assert report["days_remaining"] == 0
    assert "Run the complete walk-forward" in report["next_action"]


def test_data_source_error_is_reported_as_critical_gap_instead_of_empty_data():
    observed = CUTOFF + timedelta(days=1)
    row = _row(records=0, latest_time=None)
    row["latest_time"] = None
    row["query_error"] = "OperationalError: no such table"

    report = assess_data_readiness([row], cutoff=CUTOFF, observed_at=observed)

    assert report["status"] == "DATA_GAPS"
    assert report["critical_gap_count"] == 1
    assert report["scopes"][0]["status"] == "DATA_SOURCE_ERROR"


def test_inventory_reports_missing_schema_without_crashing_or_accessing_outcomes():
    session = sessionmaker(bind=create_engine("sqlite:///:memory:"))()

    rows = collect_inventory(session, cutoff=CUTOFF, symbols=("BTCUSDT",))
    report = assess_data_readiness(
        rows,
        cutoff=CUTOFF,
        observed_at=CUTOFF + timedelta(days=1),
    )

    assert len(rows) == 17
    assert all(item["query_error"].startswith("MissingTable:") for item in rows)
    assert report["status"] == "DATA_GAPS"
    assert report["outcome_data_accessed"] is False


def test_readiness_script_supports_direct_execution_without_pythonpath(tmp_path):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "check_prospective_holdout_readiness.py"),
            "--help",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "outcome-blind readiness report" in result.stdout
