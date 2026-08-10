from datetime import datetime

from app.jobs.deterministic_pipeline_job import _invoke_stage
from app.pipeline.context import PipelineContext


def test_stage_invocation_propagates_one_immutable_context():
    context = PipelineContext("generation-001", datetime(2026, 7, 27, 12, 0, 0))
    seen = []

    def stage(*, context):
        seen.append(context)
        return {"status": "COMPLETED"}

    result = _invoke_stage(stage, context)

    assert result["status"] == "COMPLETED"
    assert seen == [context]
    assert context.as_metadata() == {
        "data_generation_id": "generation-001",
        "source_cutoff": "2026-07-27T12:00:00",
    }


def test_legacy_stage_without_context_remains_compatible():
    assert _invoke_stage(lambda: {"status": "COMPLETED"}, PipelineContext("g", datetime.utcnow()))[
        "status"
    ] == "COMPLETED"
