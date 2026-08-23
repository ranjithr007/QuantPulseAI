"""Prospective, evidence-only evaluation of frozen loss hypotheses.

The discovery sample ended at the manifest cutoff.  This module evaluates the
pre-registered hypotheses only on later trades and never changes eligibility,
paper execution, or live execution policy.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.backtesting.loss_cluster_analysis import load_walk_forward_trades


EVALUATOR_VERSION = "prospective_walk_forward_holdout_v1"
REPORT_JSON_NAME = "prospective_holdout_report.json"
REPORT_MARKDOWN_NAME = "prospective_holdout_report.md"
DEFAULT_MANIFEST_PATH = Path(__file__).with_name("holdout_hypotheses_v1.json")
PROHIBITED_SELECTOR_FIELDS = {
    "pnl",
    "pnl_percent",
    "gross_pnl",
    "exit_reason",
    "exit_path",
    "exit_legs",
    "result",
}
ALLOWED_SELECTOR_FIELDS = {"symbol", "timeframe", "side", "regime", "confidence_band"}
REQUIRED_THRESHOLD_FIELDS = {
    "minimum_calendar_days",
    "minimum_holdout_trades",
    "minimum_affected_trades",
    "minimum_retained_trades",
    "minimum_retained_percent",
    "minimum_filtered_profit_factor",
}


def generate_prospective_holdout_artifacts(
    consolidated_path,
    *,
    output_dir=None,
    manifest_path=None,
):
    """Validate a complete run and persist its post-cutoff holdout report."""

    consolidated_path = Path(consolidated_path)
    consolidated = json.loads(consolidated_path.read_text(encoding="utf-8"))
    trades, ingestion = load_walk_forward_trades(
        consolidated,
        consolidated_path=consolidated_path,
    )
    manifest_path = Path(manifest_path or DEFAULT_MANIFEST_PATH)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    report = build_prospective_holdout_report(
        consolidated,
        trades,
        manifest,
        ingestion=ingestion,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
    target_dir = Path(output_dir) if output_dir else consolidated_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / REPORT_JSON_NAME
    markdown_path = target_dir / REPORT_MARKDOWN_NAME
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_prospective_holdout_report(report), encoding="utf-8")
    return {
        "report": report,
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
    }


def build_prospective_holdout_report(
    consolidated,
    trades,
    manifest,
    *,
    ingestion=None,
    manifest_sha256=None,
):
    """Compare the unchanged baseline with each frozen research filter."""

    _validate_manifest(manifest)
    cutoff = _parse_timestamp(manifest["discovery_cutoff"])
    as_of = _parse_timestamp(consolidated.get("as_of"))
    thresholds = dict(manifest["evidence_thresholds"])
    dated_trades = []
    missing_entry_times = 0
    for trade in trades:
        entry_time = _optional_timestamp(trade.get("entry_time"))
        if entry_time is None:
            missing_entry_times += 1
            continue
        if entry_time > cutoff:
            dated_trades.append(trade)

    calendar_days = max(0.0, (as_of - cutoff).total_seconds() / 86400)
    global_failures = []
    if as_of <= cutoff:
        global_failures.append("walk-forward cutoff has not advanced beyond discovery cutoff")
    if missing_entry_times:
        global_failures.append(
            f"{missing_entry_times} ledger trades have no valid entry_time"
        )
    if calendar_days < float(thresholds["minimum_calendar_days"]):
        global_failures.append(
            f"holdout spans {calendar_days:.2f} days; minimum is "
            f"{thresholds['minimum_calendar_days']}"
        )
    if len(dated_trades) < int(thresholds["minimum_holdout_trades"]):
        global_failures.append(
            f"holdout has {len(dated_trades)} trades; minimum is "
            f"{thresholds['minimum_holdout_trades']}"
        )

    baseline = _metrics(dated_trades)
    evaluations = []
    for hypothesis in manifest["hypotheses"]:
        affected = [
            trade for trade in dated_trades if _matches(trade, hypothesis["exclude_when"])
        ]
        retained = [
            trade for trade in dated_trades if not _matches(trade, hypothesis["exclude_when"])
        ]
        affected_metrics = _metrics(affected)
        filtered_metrics = _metrics(retained)
        retained_percent = round(
            len(retained) / len(dated_trades) * 100 if dated_trades else 0.0,
            2,
        )
        failures = list(global_failures)
        if len(affected) < int(thresholds["minimum_affected_trades"]):
            failures.append(
                f"affected sample has {len(affected)} trades; minimum is "
                f"{thresholds['minimum_affected_trades']}"
            )
        if len(retained) < int(thresholds["minimum_retained_trades"]):
            failures.append(
                f"retained sample has {len(retained)} trades; minimum is "
                f"{thresholds['minimum_retained_trades']}"
            )
        if retained_percent < float(thresholds["minimum_retained_percent"]):
            failures.append(
                f"retained share is {retained_percent}%; minimum is "
                f"{thresholds['minimum_retained_percent']}%"
            )

        delta_net_pnl = round(filtered_metrics["net_pnl"] - baseline["net_pnl"], 2)
        delta_win_rate = round(filtered_metrics["win_rate"] - baseline["win_rate"], 2)
        delta_profit_factor = _metric_delta(
            filtered_metrics["profit_factor"], baseline["profit_factor"]
        )
        promising = (
            not failures
            and affected_metrics["net_pnl"] < 0
            and delta_net_pnl > 0
            and filtered_metrics["net_pnl"] > 0
            and _profit_factor_at_least(
                filtered_metrics,
                float(thresholds["minimum_filtered_profit_factor"]),
            )
        )
        if failures:
            decision = "INSUFFICIENT_EVIDENCE"
        elif promising:
            decision = "PROMISING_RESEARCH"
        else:
            decision = "REJECTED_RESEARCH"
        evaluations.append(
            {
                "hypothesis_id": hypothesis["id"],
                "label": hypothesis["label"],
                "exclude_when": hypothesis["exclude_when"],
                "decision": decision,
                "evidence_failures": failures,
                "affected": affected_metrics,
                "filtered": filtered_metrics,
                "trades_excluded": len(affected),
                "retained_percent": retained_percent,
                "delta_net_pnl": delta_net_pnl,
                "delta_win_rate": delta_win_rate,
                "delta_profit_factor": delta_profit_factor,
            }
        )

    has_reviewable_evaluation = any(
        item["decision"] != "INSUFFICIENT_EVIDENCE" for item in evaluations
    )
    status = (
        "RESEARCH_REVIEW_READY"
        if not global_failures and has_reviewable_evaluation
        else "INSUFFICIENT_EVIDENCE"
    )
    if missing_entry_times:
        status = "INVALID_EVIDENCE"
    return {
        "source": EVALUATOR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "manifest": {
            "version": manifest["manifest_version"],
            "sha256": manifest_sha256,
            "frozen_at": manifest["frozen_at"],
            "discovery_cutoff": manifest["discovery_cutoff"],
        },
        "walk_forward_as_of": consolidated.get("as_of"),
        "holdout_calendar_days": round(calendar_days, 4),
        "holdout_trade_count": len(dated_trades),
        "baseline": baseline,
        "evidence_thresholds": thresholds,
        "evidence_failures": global_failures,
        "ingestion": dict(ingestion or {}),
        "evaluations": evaluations,
        "governance": {
            "production_policy_changed": False,
            "paper_policy_changed": False,
            "promotion_allowed": False,
            "automatic_filter_activation": False,
            "post_cutoff_entries_only": True,
            "exit_outcomes_allowed_as_selectors": False,
            "note": (
                "A PROMISING_RESEARCH result requires human review and a separate "
                "governed change. This evaluator cannot activate a trading filter."
            ),
        },
    }


def markdown_prospective_holdout_report(report):
    lines = [
        "# QuantPulseAI Prospective Holdout Report",
        "",
        f"- Status: {report['status']}",
        f"- Frozen discovery cutoff: {report['manifest']['discovery_cutoff']}",
        f"- Walk-forward cutoff: {report.get('walk_forward_as_of')}",
        f"- Holdout span: {report['holdout_calendar_days']} days",
        f"- Post-cutoff trades: {report['holdout_trade_count']}",
        f"- Manifest SHA-256: {report['manifest'].get('sha256') or 'not supplied'}",
        "- Paper or production policy changed: No",
        "- Automatic promotion allowed: No",
        "",
    ]
    if report["evidence_failures"]:
        lines.extend(["## Evidence not yet sufficient", ""])
        lines.extend(f"- {item}" for item in report["evidence_failures"])
        lines.append("")
    baseline = report["baseline"]
    lines.extend(
        [
            "## Unchanged baseline",
            "",
            f"- Trades: {baseline['trade_count']}",
            f"- Win rate: {baseline['win_rate']}%",
            f"- Net PnL: {baseline['net_pnl']}",
            f"- Profit factor: {_display(baseline['profit_factor'])}",
            "",
            "## Frozen hypothesis comparisons",
            "",
            "| ID | Hypothesis | Decision | Excluded | Retained % | Filtered PnL | Filtered PF | Delta PnL |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in report["evaluations"]:
        lines.append(
            f"| {item['hypothesis_id']} | {item['label']} | {item['decision']} | "
            f"{item['trades_excluded']} | {item['retained_percent']} | "
            f"{item['filtered']['net_pnl']} | {_display(item['filtered']['profit_factor'])} | "
            f"{item['delta_net_pnl']} |"
        )
    lines.extend(
        [
            "",
            "## Governance conclusion",
            "",
            report["governance"]["note"],
            "No paper or live trading rule is changed by this report.",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_manifest(manifest):
    required = {"manifest_version", "frozen_at", "discovery_cutoff", "evidence_thresholds", "hypotheses"}
    missing = required.difference(manifest)
    if missing:
        raise ValueError("Holdout manifest is missing: " + ", ".join(sorted(missing)))
    _parse_timestamp(manifest["frozen_at"])
    cutoff = _parse_timestamp(manifest["discovery_cutoff"])
    if _parse_timestamp(manifest["frozen_at"]) > cutoff:
        raise ValueError("Holdout hypotheses must be frozen no later than the discovery cutoff")
    threshold_fields = set(manifest["evidence_thresholds"])
    missing_thresholds = REQUIRED_THRESHOLD_FIELDS.difference(threshold_fields)
    if missing_thresholds:
        raise ValueError(
            "Holdout evidence thresholds are missing: "
            + ", ".join(sorted(missing_thresholds))
        )
    ids = set()
    for hypothesis in manifest["hypotheses"]:
        hypothesis_id = str(hypothesis.get("id") or "").strip()
        if not hypothesis_id or hypothesis_id in ids:
            raise ValueError("Holdout hypothesis IDs must be present and unique")
        ids.add(hypothesis_id)
        selectors = _selector_fields(hypothesis.get("exclude_when"))
        prohibited = selectors.intersection(PROHIBITED_SELECTOR_FIELDS)
        if prohibited:
            raise ValueError(
                "Outcome leakage is prohibited in holdout selectors: "
                + ", ".join(sorted(prohibited))
            )
        unsupported = selectors.difference(ALLOWED_SELECTOR_FIELDS)
        if unsupported:
            raise ValueError(
                "Unsupported holdout selector fields: "
                + ", ".join(sorted(unsupported))
            )


def _selector_fields(selector):
    if not isinstance(selector, dict):
        raise ValueError("Holdout selector must be an object")
    fields = set()
    if "any_of" in selector and len(selector) != 1:
        raise ValueError("any_of cannot be combined with sibling selector fields")
    for key, value in selector.items():
        if key == "any_of":
            if not isinstance(value, list) or not value:
                raise ValueError("any_of must contain at least one selector")
            for child in value:
                fields.update(_selector_fields(child))
        else:
            fields.add(str(key))
    return fields


def _matches(trade, selector):
    if "any_of" in selector:
        return any(_matches(trade, child) for child in selector["any_of"])
    return all(_normalise(trade.get(key)) == _normalise(value) for key, value in selector.items())


def _metrics(trades):
    pnl = [_number(item.get("pnl")) for item in trades]
    wins = sum(value > 0 for value in pnl)
    losses = sum(value < 0 for value in pnl)
    gross_profit = sum(value for value in pnl if value > 0)
    gross_loss = abs(sum(value for value in pnl if value < 0))
    count = len(trades)
    return {
        "trade_count": count,
        "wins": wins,
        "losses": losses,
        "breakeven": count - wins - losses,
        "win_rate": round(wins / count * 100 if count else 0.0, 2),
        "net_pnl": round(sum(pnl), 2),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
    }


def _metric_delta(value, baseline):
    if value is None or baseline is None:
        return None
    return round(value - baseline, 4)


def _profit_factor_at_least(metrics, minimum):
    """Treat positive PnL with no losing trades as an infinite profit factor."""

    value = metrics.get("profit_factor")
    if value is None:
        return metrics.get("net_pnl", 0.0) > 0 and metrics.get("losses", 0) == 0
    return value >= minimum


def _parse_timestamp(value):
    parsed = _optional_timestamp(value)
    if parsed is None:
        raise ValueError(f"Invalid required UTC timestamp: {value!r}")
    return parsed


def _optional_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalise(value):
    return str(value or "").strip().upper()


def _number(value):
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _display(value):
    return "-" if value is None else str(value)
