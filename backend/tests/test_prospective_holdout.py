import json

import pytest

from app.backtesting.prospective_holdout import build_prospective_holdout_report
from app.backtesting.prospective_holdout import generate_prospective_holdout_artifacts


def _manifest(**threshold_overrides):
    thresholds = {
        "minimum_calendar_days": 7,
        "minimum_holdout_trades": 30,
        "minimum_affected_trades": 10,
        "minimum_retained_trades": 20,
        "minimum_retained_percent": 70,
        "minimum_filtered_profit_factor": 1.0,
        **threshold_overrides,
    }
    return {
        "manifest_version": "test_v1",
        "frozen_at": "2026-08-23T16:00:00+00:00",
        "discovery_cutoff": "2026-08-23T16:00:00+00:00",
        "evidence_thresholds": thresholds,
        "hypotheses": [
            {
                "id": "H01",
                "label": "Exclude SOL 4h longs",
                "exclude_when": {
                    "symbol": "SOLUSDT",
                    "timeframe": "4h",
                    "side": "LONG",
                },
            }
        ],
    }


def _trade(pnl, entry_time, *, symbol="BTCUSDT", timeframe="1h", side="LONG"):
    return {
        "pnl": pnl,
        "entry_time": entry_time,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
    }


def test_holdout_uses_only_entries_strictly_after_frozen_cutoff():
    trades = [
        _trade(100, "2026-08-23T15:59:59+00:00"),
        _trade(100, "2026-08-23T16:00:00+00:00"),
        _trade(-5, "2026-08-23T16:00:01+00:00", symbol="SOLUSDT", timeframe="4h"),
    ]
    report = build_prospective_holdout_report(
        {"as_of": "2026-08-24T16:00:00+00:00"},
        trades,
        _manifest(
            minimum_calendar_days=0,
            minimum_holdout_trades=1,
            minimum_affected_trades=1,
            minimum_retained_trades=0,
            minimum_retained_percent=0,
        ),
    )

    assert report["holdout_trade_count"] == 1
    assert report["baseline"]["net_pnl"] == -5
    assert report["governance"]["post_cutoff_entries_only"] is True


def test_promising_result_requires_sufficient_new_untouched_evidence():
    trades = []
    for index in range(10):
        trades.append(
            _trade(
                -10,
                f"2026-08-24T{index:02d}:00:00+00:00",
                symbol="SOLUSDT",
                timeframe="4h",
            )
        )
    for index in range(24):
        trades.append(_trade(10, f"2026-08-25T{index:02d}:00:00+00:00"))

    report = build_prospective_holdout_report(
        {"as_of": "2026-08-31T16:00:01+00:00"},
        trades,
        _manifest(),
    )

    evaluation = report["evaluations"][0]
    assert report["status"] == "RESEARCH_REVIEW_READY"
    assert evaluation["decision"] == "PROMISING_RESEARCH"
    assert evaluation["filtered"]["net_pnl"] == 240
    assert evaluation["delta_net_pnl"] == 100
    assert report["governance"]["promotion_allowed"] is False
    assert report["governance"]["paper_policy_changed"] is False


def test_small_affected_sample_cannot_pass_even_when_filter_looks_better():
    trades = [
        _trade(-100, "2026-08-24T00:00:00+00:00", symbol="SOLUSDT", timeframe="4h")
    ] + [
        _trade(10, f"2026-08-25T{index:02d}:00:00+00:00") for index in range(20)
    ]
    report = build_prospective_holdout_report(
        {"as_of": "2026-08-31T16:00:01+00:00"},
        trades,
        _manifest(minimum_holdout_trades=20),
    )

    assert report["evaluations"][0]["decision"] == "INSUFFICIENT_EVIDENCE"
    assert "affected sample" in " ".join(report["evaluations"][0]["evidence_failures"])


def test_outcome_fields_are_rejected_as_leaky_selectors():
    manifest = _manifest()
    manifest["hypotheses"][0]["exclude_when"] = {"exit_reason": "STOP_LOSS"}

    with pytest.raises(ValueError, match="Outcome leakage"):
        build_prospective_holdout_report(
            {"as_of": "2026-08-31T16:00:01+00:00"}, [], manifest
        )


def test_unknown_selector_fields_are_rejected_fail_closed():
    manifest = _manifest()
    manifest["hypotheses"][0]["exclude_when"] = {"future_feature": "VALUE"}

    with pytest.raises(ValueError, match="Unsupported holdout selector"):
        build_prospective_holdout_report(
            {"as_of": "2026-08-31T16:00:01+00:00"}, [], manifest
        )


def test_global_sample_does_not_hide_insufficient_hypothesis_sample():
    trades = [
        _trade(5, f"2026-08-25T{index % 24:02d}:00:00+00:00")
        for index in range(30)
    ]
    report = build_prospective_holdout_report(
        {"as_of": "2026-08-31T16:00:01+00:00"}, trades, _manifest()
    )

    assert report["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["evaluations"][0]["decision"] == "INSUFFICIENT_EVIDENCE"


def test_missing_entry_timestamp_invalidates_evidence():
    report = build_prospective_holdout_report(
        {"as_of": "2026-08-31T16:00:01+00:00"},
        [{"pnl": 10, "symbol": "BTCUSDT", "timeframe": "1h", "side": "LONG"}],
        _manifest(minimum_holdout_trades=0, minimum_retained_trades=0),
    )

    assert report["status"] == "INVALID_EVIDENCE"
    assert "no valid entry_time" in " ".join(report["evidence_failures"])


def test_artifact_generation_reports_no_evidence_at_discovery_cutoff(tmp_path):
    artifact_dir = tmp_path / "phase2_validation_reports"
    run_dir = tmp_path / "complete_walk_forward_test"
    artifact_dir.mkdir()
    run_dir.mkdir()
    artifact_id = "BTCUSDT_1h_LONG_test"
    (artifact_dir / f"{artifact_id}.json").write_text(
        json.dumps(
            {
                "scope": {"symbol": "BTCUSDT", "timeframe": "1h", "signal": "LONG"},
                "walk_forward_result": {
                    "out_of_sample": {
                        "trades": [_trade(5, "2026-08-23T15:00:00+00:00")]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    consolidated_path = run_dir / "consolidated_walk_forward_report.json"
    consolidated_path.write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "as_of": "2026-08-23T16:00:00+00:00",
                "scope": {"side_run_count": 1},
                "records": [
                    {
                        "status": "COMPLETED",
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "signal": "LONG",
                        "oos_total_trades": 1,
                        "artifact": {"artifact_id": artifact_id},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    generated = generate_prospective_holdout_artifacts(consolidated_path)

    assert generated["report"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert generated["report"]["holdout_trade_count"] == 0
    assert generated["report"]["manifest"]["sha256"]
    assert "No paper or live trading rule is changed" in open(
        generated["markdown_path"], encoding="utf-8"
    ).read()
