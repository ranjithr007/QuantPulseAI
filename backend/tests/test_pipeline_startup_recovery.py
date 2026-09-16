from unittest.mock import Mock, patch

from app.database.pipeline_startup_recovery import recover_abandoned_pipeline_runs


def test_startup_recovery_repairs_abandoned_rows_and_closes_session():
    db = Mock()
    repository = Mock()
    repository.recover_stale_running.return_value = {
        "recovered_pipelines": 1,
        "recovered_jobs": 1,
        "pipeline_ids": ["pipeline-old"],
    }

    with patch(
        "app.database.pipeline_startup_recovery.SessionLocal",
        return_value=db,
    ), patch(
        "app.database.pipeline_startup_recovery.PipelineRunRepository",
        return_value=repository,
    ):
        result = recover_abandoned_pipeline_runs(stale_after_seconds=1800)

    assert result["recovered_pipelines"] == 1
    repository.recover_stale_running.assert_called_once_with(
        db,
        stale_after_seconds=1800,
    )
    db.close.assert_called_once_with()


def test_startup_recovery_fails_safe_when_database_is_unavailable():
    db = Mock()
    repository = Mock()
    repository.recover_stale_running.side_effect = RuntimeError("boom")

    with patch(
        "app.database.pipeline_startup_recovery.SessionLocal",
        return_value=db,
    ), patch(
        "app.database.pipeline_startup_recovery.PipelineRunRepository",
        return_value=repository,
    ), patch("builtins.print"):
        result = recover_abandoned_pipeline_runs()

    assert result["recovered_pipelines"] == 0
    assert result["error"] == "boom"
    db.rollback.assert_called_once_with()
    db.close.assert_called_once_with()
