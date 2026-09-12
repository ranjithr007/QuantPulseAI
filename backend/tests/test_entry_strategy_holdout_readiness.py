import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.api.v1 import strategy_api
from app.backtesting.entry_strategy_holdout_readiness import (
    assess_entry_holdout_readiness,
    load_manifest,
    validate_manifest,
)
from test_strategy_attribution import _session_factory


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MANIFEST, _ = load_manifest()
CUTOFF = datetime.fromisoformat(MANIFEST["holdout_start_exclusive"])
PROFILE = MANIFEST["required_entry_evidence"]["profile"]


def _entry(candidate, sequence, *, opened_at=None, evidence=True):
    return {
        "trade_id": sequence,
        "strategy_id": candidate["strategy_id"],
        "strategy_version": candidate["strategy_version"],
        "symbol": ("BTCUSDT", "ETHUSDT", "SOLUSDT")[sequence % 3],
        "side": "LONG" if sequence % 2 else "SHORT",
        "entry_timeframe": ("1h", "2h", "4h", "1d")[sequence % 4],
        "opened_at": opened_at or CUTOFF + timedelta(hours=sequence + 1),
        "execution_evidence": (
            {"entry_quality_profile": PROFILE, "entry_quality_passed": True}
            if evidence
            else {}
        ),
    }


def test_outcome_review_remains_locked_until_every_frozen_candidate_is_ready():
    observed = CUTOFF + timedelta(days=10)
    entries = []
    for candidate in MANIFEST["candidates"]:
        entries.extend(_entry(candidate, index) for index in range(30))
    report = assess_entry_holdout_readiness(entries, MANIFEST, observed_at=observed)

    assert report["status"] == "OUTCOME_REVIEW_READY"
    assert report["outcome_review_unlocked"] is True
    assert report["ready_candidate_count"] == 3
    assert report["governance"]["outcome_columns_accessed"] is False
    assert report["governance"]["automatic_promotion_allowed"] is False

    report = assess_entry_holdout_readiness(entries[:-1], MANIFEST, observed_at=observed)
    assert report["status"] == "COLLECTING_PROSPECTIVE_ENTRIES"
    assert report["outcome_review_unlocked"] is False


def test_cutoff_and_48_hour_maturity_are_strict():
    candidate = MANIFEST["candidates"][0]
    observed = CUTOFF + timedelta(days=8)
    entries = [
        _entry(candidate, 1, opened_at=CUTOFF),
        _entry(candidate, 2, opened_at=CUTOFF + timedelta(microseconds=1)),
        _entry(candidate, 3, opened_at=observed - timedelta(hours=48)),
        _entry(candidate, 4, opened_at=observed - timedelta(hours=48) + timedelta(microseconds=1)),
    ]
    report = assess_entry_holdout_readiness(entries, MANIFEST, observed_at=observed)
    cohort = report["cohorts"][0]

    assert cohort["post_cutoff_entries"] == 3
    assert cohort["mature_entries"] == 2
    assert cohort["immature_entries"] == 1


def test_invalid_mature_entry_evidence_blocks_readiness():
    observed = CUTOFF + timedelta(days=10)
    entries = []
    for candidate in MANIFEST["candidates"]:
        entries.extend(_entry(candidate, index) for index in range(30))
    entries[0]["execution_evidence"] = {}
    report = assess_entry_holdout_readiness(entries, MANIFEST, observed_at=observed)

    assert report["status"] == "INVALID_ENTRY_EVIDENCE"
    assert report["outcome_review_unlocked"] is False
    assert report["cohorts"][0]["invalid_mature_entry_evidence"] == 1


def test_manifest_rejects_duplicate_or_mutable_candidate():
    duplicate = deepcopy(MANIFEST)
    duplicate["candidates"].append(deepcopy(duplicate["candidates"][0]))
    with pytest.raises(ValueError, match="unique"):
        validate_manifest(duplicate)

    mutable = deepcopy(MANIFEST)
    mutable["candidates"][0] = {
        "strategy_id": "CORE_SIGNAL",
        "strategy_version": "core_signal_v1",
        "label": "Not an immutable experiment",
    }
    with pytest.raises(ValueError, match="not immutable"):
        validate_manifest(mutable)


def test_readiness_script_supports_direct_execution_without_pythonpath(tmp_path):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "check_entry_strategy_holdout_readiness.py"),
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
    assert "outcome-blind V2F" in result.stdout


def test_strategy_summary_exposes_automatic_outcome_blind_progress(monkeypatch):
    factory = _session_factory()
    monkeypatch.setattr(strategy_api, "SessionLocal", factory)

    summary = strategy_api.get_strategy_summary(
        strategy_id="CORE_SIGNAL_ENTRY",
        since_days=30,
        candidate_limit=1,
        include_ledger=False,
    )

    holdout = summary["entry_strategy_holdout"]
    assert holdout["contract"] == "entry_strategy_holdout_readiness_v2f"
    assert holdout["governance"]["outcome_columns_accessed"] is False
    assert holdout["governance"]["automatic_promotion_allowed"] is False
    assert {item["strategy_id"] for item in holdout["cohorts"]} == {
        "CORE_SIGNAL_ENTRY",
        "MARKET_MOVE_ENTRY",
        "REGIME_TREND_ENTRY",
    }
