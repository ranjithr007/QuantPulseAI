"""Evidence-only loss attribution for governed walk-forward artifacts.

The analysis deliberately does not change entry or risk policy.  It turns the
full out-of-sample trade ledger into research hypotheses that must be verified
on a later, untouched holdout window before any production gate is changed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ANALYSIS_VERSION = "walk_forward_loss_cluster_v1"
REPORT_JSON_NAME = "walk_forward_loss_cluster_report.json"
REPORT_MARKDOWN_NAME = "walk_forward_loss_cluster_report.md"
MIN_HYPOTHESIS_TRADES = 5


def generate_loss_cluster_artifacts(consolidated_path, *, output_dir=None):
    """Load one consolidated run, validate its ledger, and persist the audit."""

    consolidated_path = Path(consolidated_path)
    consolidated = json.loads(consolidated_path.read_text(encoding="utf-8"))
    trades, ingestion = load_walk_forward_trades(
        consolidated,
        consolidated_path=consolidated_path,
    )
    report = build_loss_cluster_report(
        consolidated,
        trades,
        ingestion=ingestion,
    )
    target_dir = Path(output_dir) if output_dir else consolidated_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / REPORT_JSON_NAME
    markdown_path = target_dir / REPORT_MARKDOWN_NAME
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_loss_cluster_report(report), encoding="utf-8")
    return {
        "report": report,
        "json_path": str(json_path.resolve()),
        "markdown_path": str(markdown_path.resolve()),
    }


def load_walk_forward_trades(consolidated, *, consolidated_path=None):
    """Load all referenced full artifacts and reject incomplete evidence."""

    report_path = Path(consolidated_path) if consolidated_path else None
    records = [
        item
        for item in consolidated.get("records") or []
        if item.get("status") == "COMPLETED"
    ]
    trades = []
    missing_artifacts = []
    artifact_ids = []
    engine_versions = set()

    for record in records:
        artifact = dict(record.get("artifact") or {})
        artifact_id = str(artifact.get("artifact_id") or "").strip()
        artifact_path = _resolve_artifact_path(
            artifact,
            consolidated_path=report_path,
        )
        if artifact_path is None:
            missing_artifacts.append(artifact_id or _scope_label(record))
            continue
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        result = dict(payload.get("walk_forward_result") or {})
        out_of_sample = dict(result.get("out_of_sample") or {})
        scope = dict(payload.get("scope") or {})
        artifact_ids.append(artifact_id or artifact_path.stem)
        engine_version = str(result.get("backtest_engine_version") or "").strip()
        if engine_version:
            engine_versions.add(engine_version)
        for trade in out_of_sample.get("trades") or []:
            trades.append(
                {
                    **trade,
                    "symbol": str(scope.get("symbol") or record.get("symbol") or "UNKNOWN").upper(),
                    "timeframe": str(scope.get("timeframe") or record.get("timeframe") or "UNKNOWN"),
                    "side": str(trade.get("side") or scope.get("signal") or record.get("signal") or "UNKNOWN").upper(),
                    "artifact_id": artifact_id or artifact_path.stem,
                }
            )

    expected_trades = sum(int(item.get("oos_total_trades") or 0) for item in records)
    if missing_artifacts:
        raise ValueError(
            "Loss analysis requires every completed full artifact; missing: "
            + ", ".join(sorted(missing_artifacts))
        )
    if len(trades) != expected_trades:
        raise ValueError(
            f"Trade-ledger mismatch: consolidated={expected_trades}, loaded={len(trades)}"
        )

    return trades, {
        "completed_scope_records": len(records),
        "loaded_artifacts": len(artifact_ids),
        "expected_trades": expected_trades,
        "loaded_trades": len(trades),
        "ledger_complete": len(trades) == expected_trades,
        "artifact_ids": sorted(artifact_ids),
        "engine_versions": sorted(engine_versions),
    }


def build_loss_cluster_report(consolidated, trades, *, ingestion=None):
    enriched = [_enrich_trade(item) for item in trades]
    overall = _metrics(enriched)
    dimensions = {
        "symbol": _breakdown(enriched, lambda item: item["symbol"]),
        "timeframe": _breakdown(enriched, lambda item: item["timeframe"]),
        "side": _breakdown(enriched, lambda item: item["side"]),
        "regime": _breakdown(enriched, lambda item: item["regime"]),
        "confidence_band": _breakdown(
            enriched,
            lambda item: item["confidence_band"],
        ),
        "exit_reason": _breakdown(enriched, lambda item: item["exit_reason"]),
        "exit_path": _breakdown(enriched, lambda item: item["exit_path"]),
        "scope": _breakdown(
            enriched,
            lambda item: f"{item['symbol']} {item['timeframe']} {item['side']}",
        ),
    }
    hypotheses = _research_hypotheses(dimensions)
    staged_count = sum(
        1
        for item in enriched
        if str((item.get("staged_exit") or {}).get("policy") or "").strip()
    )
    return {
        "source": ANALYSIS_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "walk_forward_source": consolidated.get("source"),
        "walk_forward_as_of": consolidated.get("as_of"),
        "policy": dict((consolidated.get("scope") or {}).get("grid") or {}),
        "evidence": {
            **dict(ingestion or {}),
            "staged_exit_trade_count": staged_count,
            "all_trades_use_staged_exit": staged_count == len(enriched),
            "independent_scope_warning": (
                "PnL sums combine independently replayed symbol/timeframe/direction "
                "scopes and are diagnostic, not a portfolio return."
            ),
        },
        "overall": overall,
        "breakdowns": dimensions,
        "research_hypotheses": hypotheses,
        "governance": {
            "production_policy_changed": False,
            "automatic_blockers_added": False,
            "holdout_validation_required": True,
            "promotion_allowed": False,
            "note": (
                "Clusters describe this sample only. Validate hypotheses on a later "
                "untouched cutoff before changing paper-trade eligibility."
            ),
        },
    }


def markdown_loss_cluster_report(report):
    overall = report["overall"]
    evidence = report["evidence"]
    lines = [
        "# QuantPulseAI Walk-Forward Loss-Cluster Report",
        "",
        f"- Data cutoff: {report.get('walk_forward_as_of')}",
        f"- Trades loaded: {evidence.get('loaded_trades', overall['trade_count'])}",
        f"- Ledger complete: {'Yes' if evidence.get('ledger_complete') else 'No'}",
        f"- Staged-exit parity: {'Yes' if evidence.get('all_trades_use_staged_exit') else 'No'}",
        "- Production policy changed: No",
        "- Holdout validation required: Yes",
        "",
        "## Overall diagnostic",
        "",
        f"- Trades: {overall['trade_count']}",
        f"- Wins / losses / breakeven: {overall['wins']} / {overall['losses']} / {overall['breakeven']}",
        f"- Win rate: {overall['win_rate']}%",
        f"- Net PnL: {overall['net_pnl']}",
        f"- Sum of trade PnL percentages: {overall['net_pnl_percent_sum']}%",
        f"- Profit factor: {_display(overall['profit_factor'])}",
        f"- Total modeled execution costs: {overall['execution_costs']}",
        f"- Gross-positive trades made non-positive by costs: {overall['cost_flipped_trades']}",
        "",
        f"> {evidence.get('independent_scope_warning')}",
        "",
    ]
    for dimension in (
        "symbol",
        "timeframe",
        "side",
        "regime",
        "confidence_band",
        "exit_reason",
        "exit_path",
        "scope",
    ):
        lines.extend(_markdown_breakdown(dimension, report["breakdowns"][dimension]))

    lines.extend(
        [
            "## Research hypotheses",
            "",
            "These are ranked loss clusters, not automatic trading blockers.",
            "",
            "| Rank | Dimension | Cluster | Trades | Win % | Net PnL | PF | Loss contribution % |",
            "|---:|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for index, item in enumerate(report["research_hypotheses"], start=1):
        lines.append(
            f"| {index} | {item['dimension']} | {item['cluster']} | "
            f"{item['trade_count']} | {item['win_rate']} | {item['net_pnl']} | "
            f"{_display(item['profit_factor'])} | {item['loss_contribution_percent']} |"
        )
    if not report["research_hypotheses"]:
        lines.append("| - | - | No cluster met the minimum evidence rule | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## Governance conclusion",
            "",
            report["governance"]["note"],
            "No live-trading promotion is authorized by this report.",
            "",
        ]
    )
    return "\n".join(lines)


def _resolve_artifact_path(artifact, *, consolidated_path):
    configured = str(artifact.get("json_path") or "").strip()
    if configured:
        configured_path = Path(configured)
        if configured_path.exists():
            return configured_path
    artifact_id = str(artifact.get("artifact_id") or "").strip()
    if consolidated_path and artifact_id:
        candidates = (
            consolidated_path.parent / f"{artifact_id}.json",
            consolidated_path.parent.parent / "phase2_validation_reports" / f"{artifact_id}.json",
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
    return None


def _enrich_trade(trade):
    confidence = _optional_number(trade.get("confidence"))
    legs = list(trade.get("exit_legs") or [])
    exit_path = " -> ".join(
        str(item.get("reason") or "UNKNOWN").upper() for item in legs
    ) or str(trade.get("exit_reason") or "UNKNOWN").upper()
    return {
        **trade,
        "symbol": str(trade.get("symbol") or "UNKNOWN").upper(),
        "timeframe": str(trade.get("timeframe") or "UNKNOWN"),
        "side": str(trade.get("side") or "UNKNOWN").upper(),
        "regime": str(trade.get("regime") or "UNKNOWN").upper(),
        "confidence": confidence,
        "confidence_band": _confidence_band(confidence),
        "exit_reason": str(trade.get("exit_reason") or "UNKNOWN").upper(),
        "exit_path": exit_path,
        "pnl": _number(trade.get("pnl")),
        "gross_pnl": _number(trade.get("gross_pnl")),
        "pnl_percent": _number(trade.get("pnl_percent")),
        "modeled_cost": _number((trade.get("execution_costs") or {}).get("total")),
    }


def _breakdown(trades, key_function):
    grouped = defaultdict(list)
    for trade in trades:
        grouped[str(key_function(trade))].append(trade)
    rows = []
    total_negative = abs(sum(min(item["pnl"], 0.0) for item in trades))
    for key, items in grouped.items():
        metrics = _metrics(items)
        negative = abs(sum(min(item["pnl"], 0.0) for item in items))
        rows.append(
            {
                "cluster": key,
                **metrics,
                "loss_contribution_percent": round(
                    negative / total_negative * 100 if total_negative else 0.0,
                    2,
                ),
            }
        )
    return sorted(rows, key=lambda item: (item["net_pnl"], -item["trade_count"], item["cluster"]))


def _metrics(trades):
    pnl_values = [_number(item.get("pnl")) for item in trades]
    pnl_percent_values = [_number(item.get("pnl_percent")) for item in trades]
    wins = sum(value > 0 for value in pnl_values)
    losses = sum(value < 0 for value in pnl_values)
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    costs = sum(_number((item.get("execution_costs") or {}).get("total", item.get("modeled_cost"))) for item in trades)
    cost_flipped = sum(
        _number(item.get("gross_pnl")) > 0 and _number(item.get("pnl")) <= 0
        for item in trades
    )
    count = len(trades)
    return {
        "trade_count": count,
        "wins": wins,
        "losses": losses,
        "breakeven": count - wins - losses,
        "win_rate": round(wins / count * 100 if count else 0.0, 2),
        "net_pnl": round(sum(pnl_values), 2),
        "net_pnl_percent_sum": round(sum(pnl_percent_values), 4),
        "average_pnl_percent": round(sum(pnl_percent_values) / count if count else 0.0, 4),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "execution_costs": round(costs, 2),
        "cost_flipped_trades": cost_flipped,
    }


def _research_hypotheses(dimensions):
    candidates = []
    for dimension in ("scope", "regime", "confidence_band", "exit_path"):
        for item in dimensions[dimension]:
            profit_factor = item.get("profit_factor")
            if (
                item["trade_count"] >= MIN_HYPOTHESIS_TRADES
                and item["net_pnl"] < 0
                and (profit_factor is None or profit_factor < 0.8)
            ):
                candidates.append({"dimension": dimension, **item})
    candidates.sort(
        key=lambda item: (
            item["net_pnl"],
            -item["loss_contribution_percent"],
            -item["trade_count"],
        )
    )
    return candidates


def _markdown_breakdown(name, rows):
    title = name.replace("_", " ").title()
    lines = [
        f"## By {title}",
        "",
        "| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in rows:
        lines.append(
            f"| {item['cluster']} | {item['trade_count']} | {item['win_rate']} | "
            f"{item['net_pnl']} | {item['net_pnl_percent_sum']} | "
            f"{_display(item['profit_factor'])} | {item['execution_costs']} | "
            f"{item['loss_contribution_percent']} |"
        )
    lines.append("")
    return lines


def _confidence_band(value):
    if value is None:
        return "UNKNOWN"
    if value < 40:
        return "<40"
    if value < 50:
        return "40-49.99"
    if value < 60:
        return "50-59.99"
    if value < 70:
        return "60-69.99"
    return "70+"


def _scope_label(record):
    return " ".join(
        str(record.get(key) or "UNKNOWN") for key in ("symbol", "timeframe", "signal")
    )


def _number(value):
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display(value):
    return "-" if value is None else str(value)
