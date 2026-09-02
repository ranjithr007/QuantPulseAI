from datetime import datetime
from unittest.mock import Mock, patch

from app.api.v1.paper_trade_api import record_phase2_evidence_checkpoint
from app.jobs.deterministic_pipeline_job import (
    ALWAYS_RUN_SAFETY_STAGES,
    NON_BLOCKING_STRATEGY_STAGES,
    STAGE_ORDER,
)
from app.jobs.phase2_daily_checkpoint_job import run_phase2_daily_checkpoint_job


NOW = datetime(2026, 8, 15, 23, 59)


def test_checkpoint_writer_is_idempotent_for_the_same_date():
    db = Mock()
    existing = {
        "id": 42,
        "details": {"checkpoint_date": "2026-08-15"},
    }
    event_repo = Mock()
    event_repo.list_events.return_value = [existing]

    with patch(
        "app.api.v1.paper_trade_api.DataQualityEventRepository",
        return_value=event_repo,
    ), patch(
        "app.api.v1.paper_trade_api._build_phase2_evidence_checkpoint",
    ) as build:
        result = record_phase2_evidence_checkpoint(
            db,
            checkpoint_date="2026-08-15",
            observed_at=NOW,
        )

    assert result == {
        "source": "phase2_daily_evidence_checkpoint",
        "status": "EXISTS",
        "record": existing,
    }
    build.assert_not_called()
    event_repo.record_events.assert_not_called()


def test_checkpoint_writer_persists_new_daily_evidence():
    db = Mock()
    event_repo = Mock()
    event_repo.list_events.return_value = []
    event_repo.record_events.return_value = [{"id": 43}]
    checkpoint = {
        "checkpoint_date": "2026-08-15",
        "status": "PENDING",
        "reason": "Evidence is accumulating.",
    }

    with patch(
        "app.api.v1.paper_trade_api.DataQualityEventRepository",
        return_value=event_repo,
    ), patch(
        "app.api.v1.paper_trade_api._build_phase2_evidence_checkpoint",
        return_value=checkpoint,
    ):
        result = record_phase2_evidence_checkpoint(
            db,
            checkpoint_date="2026-08-15",
            observed_at=NOW,
        )

    assert result["status"] == "RECORDED"
    event = event_repo.record_events.call_args.args[1][0]
    assert event["status"] == "PENDING"
    assert event["blocked"] is False
    assert event["details"] == checkpoint
    assert event["observed_at"] == NOW


def test_worker_records_daily_checkpoint_with_explicit_utc_date():
    db = Mock()
    checkpoint = {
        "source": "phase2_daily_evidence_checkpoint",
        "status": "RECORDED",
        "record": {"id": 42},
    }

    with patch(
        "app.jobs.phase2_daily_checkpoint_job.SessionLocal",
        return_value=db,
    ), patch(
        "app.jobs.phase2_daily_checkpoint_job.record_phase2_evidence_checkpoint",
        return_value=checkpoint,
    ) as record:
        result = run_phase2_daily_checkpoint_job(now=NOW)

    assert result["status"] == "OK"
    assert result["action"] == "recorded"
    assert result["checkpoint"] == checkpoint
    record.assert_called_once_with(
        db,
        checkpoint_date="2026-08-15",
        observed_at=NOW,
    )
    db.close.assert_called_once_with()


def test_worker_treats_existing_daily_checkpoint_as_successful_no_op():
    db = Mock()
    with patch(
        "app.jobs.phase2_daily_checkpoint_job.SessionLocal",
        return_value=db,
    ), patch(
        "app.jobs.phase2_daily_checkpoint_job.record_phase2_evidence_checkpoint",
        return_value={"status": "EXISTS", "record": {"id": 42}},
    ):
        result = run_phase2_daily_checkpoint_job(now=NOW)

    assert result["status"] == "OK"
    assert result["action"] == "exists"
    db.close.assert_called_once_with()


def test_worker_surfaces_checkpoint_failure_without_skipping_cleanup():
    db = Mock()
    with patch(
        "app.jobs.phase2_daily_checkpoint_job.SessionLocal",
        return_value=db,
    ), patch(
        "app.jobs.phase2_daily_checkpoint_job.record_phase2_evidence_checkpoint",
        side_effect=RuntimeError("checkpoint failed"),
    ):
        result = run_phase2_daily_checkpoint_job(now=NOW)

    assert result["status"] == "FAILED"
    assert result["action"] == "failed"
    assert "checkpoint failed" in result["error"]
    db.rollback.assert_called_once_with()
    db.close.assert_called_once_with()


def test_checkpoint_is_final_non_blocking_always_run_pipeline_stage():
    names = [name for name, _job in STAGE_ORDER]

    assert names[-1] == "phase2_daily_checkpoint"
    assert "phase2_daily_checkpoint" in ALWAYS_RUN_SAFETY_STAGES
    assert "phase2_daily_checkpoint" in NON_BLOCKING_STRATEGY_STAGES
