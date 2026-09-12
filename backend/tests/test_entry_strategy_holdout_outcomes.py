import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from app.backtesting import entry_strategy_holdout_outcomes as outcomes
from app.backtesting import entry_strategy_holdout_readiness as readiness_module
from app.backtesting.entry_strategy_holdout_outcomes import (
    _evaluate_frozen_cohorts,
    build_entry_holdout_outcome_report,
)
from app.backtesting.entry_strategy_holdout_readiness import load_manifest
from app.jobs import walk_forward_queue_job


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MANIFEST, _ = load_manifest()


class LockedSession:
    bind = None

    def query(self, *_args, **_kwargs):
        raise AssertionError("Outcome query must not run while V2F is locked")

    def rollback(self):
        pass


def test_locked_report_never_accesses_outcome_sources(monkeypatch):
    cutoff = MANIFEST["holdout_start_exclusive"]
    monkeypatch.setattr(outcomes, "collect_candidate_entries", lambda _db, _manifest: [])

    report = build_entry_holdout_outcome_report(
        LockedSession(),
        observed_at=outcomes._naive(cutoff) + timedelta(days=1),
    )

    assert report["status"] == "LOCKED_PENDING_PROSPECTIVE_SAMPLE"
    assert report["outcome_sources_accessed"] is False
    assert report["promotion_allowed"] is False


def test_frozen_outcome_gates_pass_and_fail_without_promoting():
    names = [
        f'{item["strategy_id"]}|{item["strategy_version"]}'
        for item in MANIFEST["candidates"]
    ]
    cohort = lambda name, **overrides: {
        "cohort": name,
        "trades": 30,
        "funding_complete_trades": 30,
        "win_rate_after_funding_percent": 60,
        "average_return_after_funding_percent": 0.2,
        "profit_factor_after_funding": 1.5,
        "target1_hits": 18,
        "pre_t1_losing_stops": 10,
        **overrides,
    }
    report = {
        "entry_cohorts": {
            "strategy_version_cohort": [
                cohort(names[0]),
                cohort(names[1], win_rate_after_funding_percent=40),
                cohort(names[2]),
            ]
        }
    }

    evaluations = _evaluate_frozen_cohorts(report, MANIFEST)

    assert evaluations[0]["decision"] == "RESEARCH_PASS"
    assert evaluations[1]["decision"] == "RESEARCH_FAIL"
    assert "win rate" in evaluations[1]["failures"][0]
    assert evaluations[2]["decision"] == "RESEARCH_PASS"


def test_all_winning_cohort_treats_missing_profit_factor_as_infinite():
    names = [
        f'{item["strategy_id"]}|{item["strategy_version"]}'
        for item in MANIFEST["candidates"]
    ]
    report = {
        "entry_cohorts": {
            "strategy_version_cohort": [
                {
                    "cohort": name,
                    "trades": 30,
                    "funding_complete_trades": 30,
                    "win_rate_after_funding_percent": 100,
                    "average_return_after_funding_percent": 0.5,
                    "profit_factor_after_funding": None,
                    "target1_hits": 30,
                    "pre_t1_losing_stops": 0,
                }
                for name in names
            ]
        }
    }

    evaluations = _evaluate_frozen_cohorts(report, MANIFEST)

    assert all(item["decision"] == "RESEARCH_PASS" for item in evaluations)
    assert all(
        item["profit_factor_interpretation"] == "INFINITE_NO_LOSING_TRADES"
        for item in evaluations
    )


def test_outcome_script_supports_direct_execution_without_pythonpath(tmp_path):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "check_entry_strategy_holdout_outcomes.py"),
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
    assert "V2G review" in result.stdout


class SchedulerSession:
    def rollback(self):
        pass

    def close(self):
        pass


def test_automatic_scheduler_waits_for_readiness_without_creating_a_job(monkeypatch):
    monkeypatch.setattr(walk_forward_queue_job, "_last_entry_holdout_readiness_at", None)
    monkeypatch.setattr(walk_forward_queue_job, "SessionLocal", SchedulerSession)
    monkeypatch.setattr(
        readiness_module,
        "build_current_entry_holdout_readiness",
        lambda _db, observed_at=None: {"outcome_review_unlocked": False},
    )
    created = []
    monkeypatch.setattr(
        walk_forward_queue_job,
        "create_automatic_walk_forward_job",
        lambda *_args, **_kwargs: created.append(True),
    )

    result = walk_forward_queue_job._enqueue_entry_holdout_outcome_job(
        force_check=True
    )

    assert result is None
    assert created == []


def test_automatic_scheduler_queues_once_and_reuses_completed_report(monkeypatch):
    monkeypatch.setattr(walk_forward_queue_job, "_last_entry_holdout_readiness_at", None)
    monkeypatch.setattr(walk_forward_queue_job, "SessionLocal", SchedulerSession)
    monkeypatch.setattr(
        readiness_module,
        "build_current_entry_holdout_readiness",
        lambda _db, observed_at=None: {
            "outcome_review_unlocked": True,
            "manifest": {"version": "v2f", "sha256": "frozen"},
        },
    )
    latest = {"status": "COMPLETED", "response": {"report": {"status": "RESEARCH_REVIEW_READY"}}}
    monkeypatch.setattr(
        walk_forward_queue_job,
        "load_latest_walk_forward_job_for_parameters",
        lambda _parameters: latest,
    )
    created = []
    monkeypatch.setattr(
        walk_forward_queue_job,
        "create_automatic_walk_forward_job",
        lambda *_args, **_kwargs: created.append(True),
    )
    assert walk_forward_queue_job._enqueue_entry_holdout_outcome_job(force_check=True) is None
    assert created == []

    latest["response"]["report"]["status"] = "INVALID_REPLAY_COVERAGE"
    monkeypatch.setattr(
        walk_forward_queue_job,
        "create_automatic_walk_forward_job",
        lambda parameters, **_kwargs: (
            {"status": "QUEUED", "parameters": parameters},
            True,
        ),
    )
    queued = walk_forward_queue_job._enqueue_entry_holdout_outcome_job(force_check=True)
    assert queued["status"] == "QUEUED"
    assert queued["parameters"]["engine"] == outcomes.OUTCOME_VERSION
