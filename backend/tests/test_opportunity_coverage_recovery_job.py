from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.deterministic_pipeline_job import ALWAYS_RUN_SAFETY_STAGES, STAGE_ORDER
from app.jobs.opportunity_coverage_recovery_job import _bounded_missing
from app.jobs.opportunity_coverage_recovery_job import _bootstrap_missing
from app.jobs.opportunity_coverage_recovery_job import _gap_signature
from app.jobs.opportunity_coverage_recovery_job import run_opportunity_coverage_recovery_job


NOW = datetime(2026, 8, 15, 15, 30)
GAP_SLOT = datetime(2026, 8, 15, 13, 0)


def _coverage(missing_count):
    return {
        "status": "GAPS_DETECTED" if missing_count else "COMPLETE",
        "missing_evaluations": missing_count,
        "missing": (
            [
                {
                    "effective_timestamp": GAP_SLOT,
                    "symbols": ["BTCUSDT", "ETHUSDT"],
                    "missing_count": 2,
                }
            ]
            if missing_count
            else []
        ),
    }


def test_worker_recovers_gaps_and_records_auditable_outcome():
    db = Mock()
    event_repo = Mock()
    event_repo.list_events.return_value = []
    symbol_repo = Mock()
    symbol_repo.get_active_symbols.return_value = [
        SimpleNamespace(symbol="BTCUSDT"),
        SimpleNamespace(symbol="ETHUSDT"),
    ]

    with patch(
        "app.jobs.opportunity_coverage_recovery_job.SessionLocal",
        return_value=db,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.DataQualityEventRepository",
        return_value=event_repo,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.SymbolRepository",
        return_value=symbol_repo,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.list_decision_snapshots",
        side_effect=[[], []],
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job._phase2_opportunity_coverage",
        side_effect=[_coverage(2), _coverage(0)],
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job._reconstruct_phase2_opportunity_snapshot",
        side_effect=lambda _db, symbol, slot: {
            "symbol": symbol,
            "effective_timestamp": slot,
            "persisted": True,
        },
    ) as reconstruct:
        result = run_opportunity_coverage_recovery_job(now=NOW)

    assert result["status"] == "OK"
    assert result["action"] == "recovered"
    assert result["attempted_count"] == 2
    assert result["persisted_count"] == 2
    assert reconstruct.call_count == 2
    statuses = [
        call.args[1][0]["status"]
        for call in event_repo.record_events.call_args_list
    ]
    assert statuses == ["ATTEMPTED", "RECOVERED"]
    db.close.assert_called_once_with()


def test_worker_observes_cooldown_for_same_unresolved_gap():
    db = Mock()
    missing = _coverage(2)["missing"]
    signature = _gap_signature(missing)
    event_repo = Mock()
    event_repo.list_events.return_value = [
        {
            "status": "UNRESOLVED",
            "created_at": NOW - timedelta(minutes=5),
            "details": {"gap_signature": signature},
        }
    ]
    symbol_repo = Mock()
    symbol_repo.get_active_symbols.return_value = [
        SimpleNamespace(symbol="BTCUSDT"),
        SimpleNamespace(symbol="ETHUSDT"),
    ]

    with patch(
        "app.jobs.opportunity_coverage_recovery_job.SessionLocal",
        return_value=db,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.DataQualityEventRepository",
        return_value=event_repo,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.SymbolRepository",
        return_value=symbol_repo,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.list_decision_snapshots",
        return_value=[],
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job._phase2_opportunity_coverage",
        return_value=_coverage(2),
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job._reconstruct_phase2_opportunity_snapshot",
    ) as reconstruct:
        result = run_opportunity_coverage_recovery_job(now=NOW)

    assert result["status"] == "OK"
    assert result["action"] == "cooldown"
    reconstruct.assert_not_called()
    event_repo.record_events.assert_not_called()


def test_recovery_is_bounded_by_evaluation_count():
    missing = [
        {
            "effective_timestamp": GAP_SLOT + timedelta(hours=index),
            "symbols": [f"SYMBOL{symbol}" for symbol in range(6)],
        }
        for index in range(10)
    ]

    bounded = _bounded_missing(missing)

    assert sum(len(item["symbols"]) for item in bounded) == 48
    assert len(bounded) == 8


def test_empty_ledger_bootstraps_complete_24_hour_window_in_bounded_batches():
    missing = _bootstrap_missing(["BTCUSDT", "ETHUSDT"], NOW)

    assert len(missing) == 24
    assert sum(item["missing_count"] for item in missing) == 48
    assert missing[-1]["effective_timestamp"] == datetime(2026, 8, 15, 14, 0)


def test_worker_seeds_empty_ledger_in_first_bounded_batch():
    db = Mock()
    event_repo = Mock()
    event_repo.list_events.return_value = []
    symbol_repo = Mock()
    symbol_repo.get_active_symbols.return_value = [
        SimpleNamespace(symbol=f"SYMBOL{index}") for index in range(6)
    ]
    not_started = {
        "status": "NOT_STARTED",
        "missing_evaluations": 0,
        "missing": [],
    }
    remaining = _coverage(96)

    with patch(
        "app.jobs.opportunity_coverage_recovery_job.SessionLocal",
        return_value=db,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.DataQualityEventRepository",
        return_value=event_repo,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.SymbolRepository",
        return_value=symbol_repo,
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job.list_decision_snapshots",
        side_effect=[[], []],
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job._phase2_opportunity_coverage",
        side_effect=[not_started, remaining],
    ), patch(
        "app.jobs.opportunity_coverage_recovery_job._reconstruct_phase2_opportunity_snapshot",
        return_value={"persisted": True},
    ) as reconstruct:
        result = run_opportunity_coverage_recovery_job(now=NOW)

    assert result["status"] == "DEGRADED"
    assert result["action"] == "unresolved"
    assert result["attempted_count"] == 48
    assert result["persisted_count"] == 48
    assert result["coverage_before"]["bootstrap_recovery"] is True
    assert reconstruct.call_count == 48


def test_recovery_runs_after_watchlist_persistence_in_worker_pipeline():
    names = [name for name, _job in STAGE_ORDER]

    assert names.index("opportunity_coverage_recovery") == names.index("watchlist_persist") + 1
    assert names.index("opportunity_coverage_recovery") < names.index("risk")
    assert "opportunity_coverage_recovery" in ALWAYS_RUN_SAFETY_STAGES
