from dataclasses import dataclass
from datetime import datetime

from app.governance.evidence_policy import govern_phase2_report


PHASE2_REPORT_VERSION = "phase2_validation_report_v1"


@dataclass(frozen=True)
class Phase2ValidationThresholds:
    out_of_sample_annualized_sharpe: float = 1.0
    max_drawdown_percent: float = 20.0
    win_rate_percent: float = 45.0
    average_reward_risk: float = 1.5
    profit_factor: float = 1.3
    regime_accuracy_percent: float = 65.0
    primary_scenario_accuracy_percent: float = 55.0
    positive_regime_group_minimum: int = 5
    paper_days_minimum: int = 90


DEFAULT_PHASE2_THRESHOLDS = Phase2ValidationThresholds()


def build_phase2_validation_report(
    walk_forward_result,
    *,
    symbol,
    timeframe,
    signal,
    thresholds=None,
    as_of=None,
    paper_measurement=None,
):
    thresholds = thresholds or DEFAULT_PHASE2_THRESHOLDS
    result = dict(walk_forward_result or {})
    contract = dict(result.get("validation_contract") or {})
    oos = dict(result.get("out_of_sample") or {})
    oos_trades = list(oos.get("trades") or [])
    payoff_ratio = _payoff_ratio(oos_trades)
    trade_return_sharpe = oos.get("sharpe_ratio")
    annualized_sharpe = oos.get("annualized_sharpe")
    regime_attribution = _regime_group_attribution(oos_trades)
    paper_report = dict(paper_measurement or {})
    paper_overall = dict(paper_report.get("overall") or {})
    paper_scenario_accuracy = dict(paper_report.get("scenario_accuracy") or {})
    paper_regime_accuracy = dict(paper_report.get("regime_accuracy") or {})
    paper_status = paper_report.get("status")
    paper_days = paper_overall.get("observation_days")

    gate_checks = [
        _gate_check(
            "walk_forward_contract_alignment",
            "PASS" if contract.get("contract_status") == "PASS" else "INSUFFICIENT_EVIDENCE",
            contract.get("contract_status"),
            "PASS",
            "required",
            note=_contract_alignment_note(contract),
        ),
        _gate_check(
            "minimum_fold_count",
            "PASS"
            if int(result.get("fold_count") or 0) >= int(contract.get("minimum_fold_requirement") or 0)
            else "INSUFFICIENT_EVIDENCE",
            int(result.get("fold_count") or 0),
            int(contract.get("minimum_fold_requirement") or 0),
            "minimum",
        ),
        _metric_gate_check(
            "out_of_sample_win_rate",
            oos.get("win_rate"),
            thresholds.win_rate_percent,
            "minimum",
        ),
        _metric_gate_check(
            "out_of_sample_average_reward_risk",
            payoff_ratio,
            thresholds.average_reward_risk,
            "minimum",
        ),
        _metric_gate_check(
            "out_of_sample_profit_factor",
            oos.get("profit_factor"),
            thresholds.profit_factor,
            "minimum",
        ),
        _metric_gate_check(
            "out_of_sample_max_drawdown",
            oos.get("max_drawdown_percent"),
            thresholds.max_drawdown_percent,
            "maximum",
        ),
        (
            _metric_gate_check(
                "out_of_sample_annualized_sharpe",
                annualized_sharpe,
                thresholds.out_of_sample_annualized_sharpe,
                "minimum",
            )
            if "annualized_sharpe" in oos
            else _gate_check(
                "out_of_sample_annualized_sharpe",
                "NOT_STARTED",
                None,
                thresholds.out_of_sample_annualized_sharpe,
                "minimum",
                note="Annualized Sharpe is not yet produced by the current walk-forward runtime. Trade-return Sharpe is available for reference only.",
            )
        ),
        _regime_accuracy_gate_check(
            paper_regime_accuracy,
            thresholds.regime_accuracy_percent,
        ),
        _scenario_accuracy_gate_check(
            paper_scenario_accuracy,
            thresholds.primary_scenario_accuracy_percent,
        ),
        _gate_check(
            "positive_edge_in_primary_regime_groups",
            "PASS"
            if regime_attribution["positive_edge_group_count"] >= thresholds.positive_regime_group_minimum
            else "FAIL"
            if regime_attribution["available_group_count"] > 0
            else "NOT_STARTED",
            regime_attribution["positive_edge_group_count"],
            thresholds.positive_regime_group_minimum,
            "minimum",
            note=(
                None
                if regime_attribution["available_group_count"] > 0
                else "Regime-group attribution is not available because no out-of-sample trades have regime labels."
            ),
        ),
        _gate_check(
            "auditable_paper_days",
            "PASS"
            if paper_days is not None and float(paper_days) >= thresholds.paper_days_minimum
            else "INSUFFICIENT_EVIDENCE",
            _round_or_none(paper_days, 4),
            thresholds.paper_days_minimum,
            "minimum",
            note=(
                None
                if paper_days is not None and float(paper_days) >= thresholds.paper_days_minimum
                else "Paper-trading evidence is missing or below the minimum observation period."
            ),
        ),
        _gate_check(
            "paper_trade_measurement_gate",
            "PASS" if paper_status == "PASS" else "FAIL" if paper_status else "INSUFFICIENT_EVIDENCE",
            paper_status,
            "PASS",
            "required",
            note=(
                None
                if paper_status == "PASS"
                else "Paper-trade measurement is not attached or does not meet its performance policy."
            ),
        ),
    ]

    architecture_gate_status = _architecture_gate_status(gate_checks)
    overall_status = _overall_report_status(contract, architecture_gate_status)
    blockers = [check["name"] for check in gate_checks if check["status"] != "PASS"]

    report = {
        "report_version": PHASE2_REPORT_VERSION,
        "generated_at": _as_of(as_of).isoformat(),
        "overall_status": overall_status,
        "scope": {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": signal,
        },
        "walk_forward": {
            "validation_status": result.get("validation_status"),
            "strategy": result.get("strategy"),
            "strategy_metadata": result.get("strategy_metadata") or {},
            "gate_diagnostics": (result.get("out_of_sample") or {}).get("gate_diagnostics") or {},
            "fold_count": int(result.get("fold_count") or 0),
            "contract": contract,
        },
        "derived_metrics": {
            "out_of_sample_total_trades": int(oos.get("total_trades") or 0),
            "out_of_sample_total_return_percent": _round_or_none(oos.get("total_return_percent"), 4),
            "out_of_sample_profit_factor": _round_or_none(oos.get("profit_factor"), 4),
            "out_of_sample_win_rate": _round_or_none(oos.get("win_rate"), 4),
            "out_of_sample_max_drawdown_percent": _round_or_none(oos.get("max_drawdown_percent"), 4),
            "out_of_sample_payoff_ratio": payoff_ratio,
            "trade_return_sharpe": _round_or_none(trade_return_sharpe, 4),
            "out_of_sample_annualized_sharpe": _round_or_none(annualized_sharpe, 4),
        },
        "paper_evidence": _paper_evidence_summary(paper_report),
        "regime_attribution": regime_attribution,
        "architecture_gate": {
            "status": architecture_gate_status,
            "passed_checks": sum(1 for check in gate_checks if check["status"] == "PASS"),
            "unavailable_checks": sum(1 for check in gate_checks if check["status"] == "NOT_STARTED"),
            "insufficient_evidence_checks": sum(
                1 for check in gate_checks if check["status"] == "INSUFFICIENT_EVIDENCE"
            ),
            "checks": gate_checks,
        },
        "blocked_by": blockers,
        "next_action": _next_action(overall_status, gate_checks),
    }
    return govern_phase2_report(report, recorded_at=as_of)


def _metric_gate_check(name, actual, threshold, comparison):
    if actual is None:
        return _gate_check(
            name,
            "INSUFFICIENT_EVIDENCE",
            None,
            threshold,
            comparison,
            note="Metric is unavailable in the current report payload.",
        )
    passed = _compare(actual, threshold, comparison)
    return _gate_check(
        name,
        "PASS" if passed else "FAIL",
        _round_or_none(actual, 4),
        threshold,
        comparison,
    )


def _paper_evidence_summary(report):
    if not report:
        return {
            "status": None,
            "measurement_version": None,
            "evidence_scope": {},
            "overall": {},
            "scenario_accuracy": {},
            "regime_accuracy": {},
        }
    overall = dict(report.get("overall") or {})
    fields = (
        "closed_trades",
        "observation_days",
        "win_rate",
        "payoff_ratio",
        "profit_factor",
        "expectancy_percent",
        "compounded_return_percent",
        "max_drawdown_percent",
    )
    return {
        "status": report.get("status"),
        "measurement_version": report.get("measurement_version"),
        "evidence_scope": report.get("evidence_scope") or {},
        "overall": {field: overall.get(field) for field in fields},
        "scenario_accuracy": report.get("scenario_accuracy") or {},
        "regime_accuracy": report.get("regime_accuracy") or {},
    }


def _scenario_accuracy_gate_check(accuracy, threshold):
    status = accuracy.get("status")
    actual = accuracy.get("accuracy_percent")
    if status == "CALCULATED" and actual is not None:
        return _metric_gate_check(
            "primary_scenario_accuracy",
            actual,
            threshold,
            "minimum",
        )
    return _gate_check(
        "primary_scenario_accuracy",
        "NOT_STARTED" if status in (None, "NOT_STARTED") else "INSUFFICIENT_EVIDENCE",
        actual,
        threshold,
        "minimum",
        note=(
            "No closed paper trades contain a persisted scenario label."
            if status in (None, "NOT_STARTED")
            else "Scenario accuracy is present but not measurable."
        ),
    )


def _regime_accuracy_gate_check(accuracy, threshold):
    status = accuracy.get("status")
    actual = accuracy.get("accuracy_percent")
    if status == "CALCULATED" and actual is not None:
        return _metric_gate_check(
            "regime_accuracy",
            actual,
            threshold,
            "minimum",
        )
    return _gate_check(
        "regime_accuracy",
        "NOT_STARTED" if status in (None, "NOT_STARTED") else "INSUFFICIENT_EVIDENCE",
        actual,
        threshold,
        "minimum",
        note=(
            "No closed paper trades have a persisted regime observation at close."
            if status in (None, "NOT_STARTED")
            else "Regime accuracy is present but not measurable."
        ),
    )


def _regime_group_attribution(trades):
    groups = {}
    for trade in list(trades or []):
        regime = str(trade.get("regime") or "UNKNOWN")
        groups.setdefault(regime, []).append(trade)

    records = []
    for regime, regime_trades in sorted(groups.items()):
        returns = [
            float(trade.get("pnl_percent"))
            for trade in regime_trades
            if trade.get("pnl_percent") is not None
        ]
        wins = [value for value in returns if value > 0]
        losses = [abs(value) for value in returns if value < 0]
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        profit_factor = round(gross_profit / gross_loss, 4) if gross_loss else None
        total_return = round(sum(returns), 4)
        records.append(
            {
                "regime": regime,
                "trades": len(returns),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round((len(wins) / len(returns)) * 100, 4) if returns else 0.0,
                "profit_factor": profit_factor,
                "total_return_percent": total_return,
                "positive_edge": bool(returns and total_return > 0 and (profit_factor is None or profit_factor >= 1.0)),
            }
        )

    return {
        "available_group_count": len(records),
        "positive_edge_group_count": sum(1 for item in records if item["positive_edge"]),
        "groups": records,
    }


def _gate_check(name, status, actual, threshold, comparison, note=None):
    return {
        "name": name,
        "status": status,
        "actual": actual,
        "threshold": threshold,
        "comparison": comparison,
        "note": note,
    }


def _compare(actual, threshold, comparison):
    actual_value = float(actual)
    threshold_value = float(threshold)
    if comparison == "minimum":
        return actual_value >= threshold_value
    if comparison == "maximum":
        return actual_value <= threshold_value
    return False


def _payoff_ratio(trades):
    returns = [float(trade.get("pnl_percent", 0) or 0) for trade in list(trades or [])]
    wins = [value for value in returns if value > 0]
    losses = [abs(value) for value in returns if value < 0]
    if not wins or not losses:
        return None
    average_win = sum(wins) / len(wins)
    average_loss = sum(losses) / len(losses)
    if average_loss == 0:
        return None
    return round(average_win / average_loss, 4)


def _architecture_gate_status(checks):
    statuses = [check["status"] for check in checks]
    if any(status == "NOT_STARTED" for status in statuses):
        return "INSUFFICIENT_EVIDENCE"
    if any(status == "INSUFFICIENT_EVIDENCE" for status in statuses):
        return "INSUFFICIENT_EVIDENCE"
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    if checks and all(status == "PASS" for status in statuses):
        return "PASS"
    return "NOT_STARTED"


def _overall_report_status(contract, architecture_gate_status):
    timeframe_status = contract.get("timeframe_status")
    contract_status = contract.get("contract_status")
    if timeframe_status in {"SUPPORTING", "NON_CANONICAL"}:
        return "PARTIAL"
    if contract_status != "PASS":
        return "INSUFFICIENT_EVIDENCE"
    if architecture_gate_status in {"PASS", "FAIL"}:
        return architecture_gate_status
    return "PARTIAL"


def _contract_alignment_note(contract):
    issues = list(contract.get("issues") or [])
    if not issues:
        return "Walk-forward configuration matches the current Phase 2 contract."
    return ", ".join(issues)


def _next_action(overall_status, checks):
    if overall_status == "PASS":
        return "Validation gates passed for this symbol/timeframe report. Continue accumulating auditable paper evidence."
    if any(check["name"] == "walk_forward_contract_alignment" and check["status"] != "PASS" for check in checks):
        return "Align the walk-forward run with the official Phase 2 timeframe and fold contract before interpreting edge results."
    if any(check["status"] == "NOT_STARTED" for check in checks):
        return "Expand validation reporting with annualized Sharpe, regime/scenario accuracy, regime-group attribution, and attached paper evidence."
    if any(check["status"] == "FAIL" for check in checks):
        return "Current out-of-sample metrics do not meet the architecture gate. Return to feature, calibration, or execution-quality improvement."
    return "Collect more evidence before making a Phase 2 gate decision."


def _round_or_none(value, digits):
    if value is None:
        return None
    return round(float(value), digits)


def _as_of(value):
    if isinstance(value, datetime):
        return value
    return datetime.utcnow()
