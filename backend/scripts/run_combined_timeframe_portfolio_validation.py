"""Build combined four-timeframe portfolio evidence from a completed matrix."""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from app.backtesting.combined_timeframe_replay import (
    build_combined_timeframe_portfolio_replay,
)
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES


RUN_VERSION = "combined_timeframe_portfolio_validation_v1"
DEFAULT_SOURCE_RUN_ID = "20260814_current_paper_policy"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-id", default=DEFAULT_SOURCE_RUN_ID)
    parser.add_argument("--initial-capital", type=float, default=10_000)
    arguments = parser.parse_args()

    outputs_root = Path(__file__).resolve().parents[1] / "outputs"
    source_dir = outputs_root / f"complete_walk_forward_{arguments.source_run_id}"
    scope_results, provenance = _load_scope_results(source_dir)
    result = build_combined_timeframe_portfolio_replay(
        scope_results,
        initial_capital=arguments.initial_capital,
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "source": RUN_VERSION,
        "generated_at": generated_at,
        "source_run_id": arguments.source_run_id,
        "source_directory": str(source_dir),
        "policy": {
            "timeframes": list(OFFICIAL_ENTRY_TIMEFRAMES),
            "selection": (
                "VALIDATED_CONFIDENCE_THEN_REWARD_RISK_THEN_TIMEFRAME_DURABILITY"
            ),
            "coin_boundary": "ONE_ACTIVE_TRADE_PER_COIN_ACROSS_ALL_TIMEFRAMES",
            "rescan": "NEXT_ELIGIBLE_CANDIDATE_ONLY_AFTER_ACTIVE_TRADE_EXIT",
            "cross_coin": "OTHER_COINS_REMAIN_INDEPENDENTLY_ELIGIBLE",
        },
        "provenance": provenance,
        "result": result,
    }

    output_dir = outputs_root / f"combined_timeframe_portfolio_{arguments.source_run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "combined_timeframe_portfolio_report.json"
    markdown_path = output_dir / "combined_timeframe_portfolio_report.md"
    json_path.write_text(
        json.dumps(payload, indent=2, default=_json_default),
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(payload), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": result["status"],
                "source_scopes": result["source_scope_count"],
                "candidate_trades": result["candidate_trade_count"],
                "selected_trades": result["selected_trade_count"],
                "symbol_active_rejections": result["symbol_active_rejections"],
                "overlap_violations": result["portfolio"]["overlap_audit"][
                    "violation_count"
                ],
                "strongest_selection_violations": result["portfolio"][
                    "strongest_selection_audit"
                ]["violation_count"],
                "confidence_tier_violations": result["confidence_tier_audit"][
                    "violation_count"
                ],
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
            },
            indent=2,
        )
    )


def _load_scope_results(source_dir):
    consolidated_path = source_dir / "consolidated_walk_forward_report.json"
    consolidated = json.loads(consolidated_path.read_text(encoding="utf-8"))
    if consolidated.get("status") != "COMPLETED":
        raise ValueError("source walk-forward report must be COMPLETED")

    scope_results = []
    provenance = []
    for record in list(consolidated.get("records") or ()):
        if record.get("status") != "COMPLETED":
            raise ValueError("all source scope records must be COMPLETED")
        artifact_path = Path(dict(record.get("artifact") or {}).get("json_path") or "")
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        walk_forward = dict(artifact.get("walk_forward_result") or {})
        trades = list(dict(walk_forward.get("out_of_sample") or {}).get("trades") or ())
        scope_results.append(
            {
                "symbol": record["symbol"],
                "timeframe": record["timeframe"],
                "signal": record["signal"],
                "trades": trades,
            }
        )
        provenance.append(
            {
                "symbol": record["symbol"],
                "timeframe": record["timeframe"],
                "signal": record["signal"],
                "artifact_id": dict(record.get("artifact") or {}).get("artifact_id"),
                "artifact_path": str(artifact_path),
                "candidate_trades": len(trades),
            }
        )
    expected = len(consolidated["scope"]["symbols"]) * len(
        OFFICIAL_ENTRY_TIMEFRAMES
    ) * 2
    if len(scope_results) != expected:
        raise ValueError(
            f"source report has {len(scope_results)} scopes; {expected} are required"
        )
    return scope_results, provenance


def _markdown_report(payload):
    result = payload["result"]
    portfolio = result["portfolio"]
    audit = portfolio["overlap_audit"]
    selection_audit = portfolio["strongest_selection_audit"]
    tier_audit = result["confidence_tier_audit"]
    lines = [
        "# QuantPulseAI Combined Timeframe Portfolio Validation",
        "",
        f"- Status: {result['status']}",
        f"- Source walk-forward run: {payload['source_run_id']}",
        f"- Governed timeframes: {', '.join(result['timeframes'])}",
        f"- Source scopes: {result['source_scope_count']}",
        f"- Candidate trades: {result['candidate_trade_count']}",
        f"- Selected trades: {result['selected_trade_count']}",
        f"- Rejected overlapping same-coin candidates: {result['symbol_active_rejections']}",
        f"- Accepted same-coin overlap violations: {audit['violation_count']}",
        f"- Contested simultaneous entries: {selection_audit['contested_entry_count']}",
        f"- Strongest-selection violations: {selection_audit['violation_count']}",
        f"- Minimum-tier trades (40-<60): {tier_audit['minimum_tier_count']}",
        f"- Maximum-tier trades (>=60): {tier_audit['maximum_tier_count']}",
        f"- Confidence-tier violations: {tier_audit['violation_count']}",
        f"- Portfolio return %: {portfolio.get('total_return_percent')}",
        f"- Portfolio max drawdown %: {portfolio.get('max_drawdown_percent')}",
        "",
        "## Per-coin arbitration",
        "",
        "| Symbol | Candidates | Selected | Same-coin blocked | Overlap violations | Return % | Max DD % |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol, replay in sorted(result["per_symbol"].items()):
        lines.append(
            "| {symbol} | {candidates} | {selected} | {blocked} | {violations} | {ret} | {dd} |".format(
                symbol=symbol,
                candidates=replay.get("total_candidates"),
                selected=replay.get("total_trades"),
                blocked=dict(replay.get("rejection_counts") or {}).get(
                    "SYMBOL_ACTIVE_POSITION",
                    0,
                ),
                violations=replay["overlap_audit"]["violation_count"],
                ret=replay.get("total_return_percent"),
                dd=replay.get("max_drawdown_percent"),
            )
        )
    lines.extend(
        [
            "",
            "## Invariant conclusion",
            "",
            (
                "PASS: the accepted historical stream contains no overlapping active "
                "trade for the same coin; other coins remain independently eligible."
                if result["status"] == "PASS"
                else "FAIL: at least one accepted same-coin overlap was detected."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


if __name__ == "__main__":
    main()
