from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime


R5_EVIDENCE_VERSION = "r5_strategy_family_evidence_v1"


@dataclass(frozen=True)
class R5ResearchThresholds:
    profit_factor_minimum: float = 1.30
    expectancy_percent_minimum: float = 0.0
    max_drawdown_percent: float = 20.0
    risk_adjusted_score_minimum: float = 1.0
    fold_count_minimum: int = 6
    profitable_fold_minimum: int = 4
    catastrophic_fold_return_percent: float = -20.0
    out_of_sample_trades_minimum: int = 150
    preferred_out_of_sample_trades: int = 300
    profit_concentration_maximum_percent: float = 40.0


def build_r5_strategy_evidence(
    walk_forward_result,
    *,
    adverse_cost_result=None,
    thresholds=None,
    prior_baseline=None,
):
    thresholds = thresholds or R5ResearchThresholds()
    result = dict(walk_forward_result or {})
    oos = dict(result.get("out_of_sample") or {})
    trades = [
        {
            **dict(trade),
            "symbol": dict(trade).get("symbol") or result.get("symbol") or "UNKNOWN",
        }
        for trade in oos.get("trades") or []
    ]
    folds = list(result.get("folds") or [])
    robustness = dict(result.get("robustness") or {})
    concentrations = _profit_concentrations(trades)
    decompositions = {
        "regime": _group_attribution(trades, lambda trade: trade.get("regime") or "UNKNOWN"),
        "confidence": _group_attribution(trades, _confidence_band),
        "symbol": _group_attribution(trades, lambda trade: trade.get("symbol") or "UNKNOWN"),
        "fold": _group_attribution(trades, lambda trade: trade.get("fold") or "UNKNOWN"),
        "loss_class": _group_attribution(
            trades,
            lambda trade: trade.get("loss_class")
            or ("WIN" if float(trade.get("pnl") or 0) > 0 else "UNCLASSIFIED"),
        ),
        "cluster": _group_attribution(trades, lambda trade: trade.get("cluster") or "UNASSIGNED"),
    }
    profitable_folds = int(
        robustness.get("profitable_folds")
        if robustness.get("profitable_folds") is not None
        else sum(
            float(dict(fold.get("out_of_sample") or {}).get("total_return_percent") or 0) > 0
            for fold in folds
        )
    )
    catastrophic_folds = [
        {
            "fold": fold.get("fold"),
            "total_return_percent": dict(fold.get("out_of_sample") or {}).get(
                "total_return_percent"
            ),
        }
        for fold in folds
        if float(
            dict(fold.get("out_of_sample") or {}).get("total_return_percent") or 0
        )
        <= thresholds.catastrophic_fold_return_percent
    ]
    risk_adjusted_score = (
        oos.get("annualized_sharpe")
        if oos.get("annualized_sharpe") is not None
        else oos.get("sharpe_ratio")
    )
    gates = [
        _numeric_gate(
            "net_profit_factor",
            oos.get("profit_factor"),
            thresholds.profit_factor_minimum,
            "minimum",
        ),
        _numeric_gate(
            "positive_net_expectancy",
            oos.get("expectancy_percent"),
            thresholds.expectancy_percent_minimum,
            "greater_than",
        ),
        _numeric_gate(
            "maximum_drawdown",
            oos.get("max_drawdown_percent"),
            thresholds.max_drawdown_percent,
            "maximum",
        ),
        _numeric_gate(
            "risk_adjusted_score",
            risk_adjusted_score,
            thresholds.risk_adjusted_score_minimum,
            "minimum",
        ),
        _numeric_gate(
            "minimum_walk_forward_folds",
            result.get("fold_count"),
            thresholds.fold_count_minimum,
            "minimum",
        ),
        _numeric_gate(
            "profitable_walk_forward_folds",
            profitable_folds,
            thresholds.profitable_fold_minimum,
            "minimum",
        ),
        _boolean_gate(
            "no_catastrophic_fold",
            not catastrophic_folds if folds else None,
            note=(
                f"Catastrophic means fold return <= "
                f"{thresholds.catastrophic_fold_return_percent}%."
            ),
        ),
        _numeric_gate(
            "minimum_out_of_sample_trades",
            oos.get("total_trades"),
            thresholds.out_of_sample_trades_minimum,
            "minimum",
        ),
        _concentration_gate("monthly_profit_concentration", concentrations["month"], thresholds),
        _concentration_gate("symbol_profit_concentration", concentrations["symbol"], thresholds),
        _concentration_gate("fold_profit_concentration", concentrations["fold"], thresholds),
        _adverse_cost_gate(result, adverse_cost_result),
    ]
    status = _overall_status(gates)
    return {
        "evidence_version": R5_EVIDENCE_VERSION,
        "status": status,
        "strategy": result.get("strategy"),
        "signal": result.get("signal"),
        "thresholds": asdict(thresholds),
        "baseline_comparison": _baseline_comparison(oos, prior_baseline),
        "summary": {
            "out_of_sample_trades": int(oos.get("total_trades") or 0),
            "preferred_sample_reached": int(oos.get("total_trades") or 0)
            >= thresholds.preferred_out_of_sample_trades,
            "profit_factor": oos.get("profit_factor"),
            "expectancy_percent": oos.get("expectancy_percent"),
            "max_drawdown_percent": oos.get("max_drawdown_percent"),
            "risk_adjusted_score": risk_adjusted_score,
            "fold_count": int(result.get("fold_count") or 0),
            "profitable_folds": profitable_folds,
            "catastrophic_folds": catastrophic_folds,
        },
        "gates": gates,
        "passed_gates": sum(gate["status"] == "PASS" for gate in gates),
        "failed_gates": sum(gate["status"] == "FAIL" for gate in gates),
        "insufficient_evidence_gates": sum(
            gate["status"] == "INSUFFICIENT_EVIDENCE" for gate in gates
        ),
        "profit_concentration": concentrations,
        "decompositions": decompositions,
        "research_policy": {
            "parameter_tuning_from_this_report": "PROHIBITED",
            "cluster_rules": "CHALLENGER_ONLY_UNTIL_UNTOUCHED_BASELINE_IMPROVEMENT",
            "high_precision_win_rate": "ASPIRATIONAL_NOT_A_STANDALONE_GATE",
        },
    }


def _group_attribution(trades, key_builder):
    groups = defaultdict(list)
    for trade in trades:
        groups[str(key_builder(trade))].append(trade)
    return [
        {
            "group": group,
            **_trade_metrics(group_trades),
        }
        for group, group_trades in sorted(groups.items())
    ]


def _trade_metrics(trades):
    pnl = [float(trade.get("pnl") or 0) for trade in trades]
    returns = [float(trade.get("pnl_percent") or 0) for trade in trades]
    wins = [value for value in pnl if value > 0]
    losses = [abs(value) for value in pnl if value < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 4) if trades else 0,
        "net_pnl": round(sum(pnl), 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "expectancy_percent": round(sum(returns) / len(returns), 4) if returns else None,
    }


def _profit_concentrations(trades):
    dimensions = {
        "month": defaultdict(float),
        "symbol": defaultdict(float),
        "fold": defaultdict(float),
    }
    total_positive_profit = 0.0
    for trade in trades:
        profit = max(0.0, float(trade.get("pnl") or 0))
        if profit <= 0:
            continue
        total_positive_profit += profit
        dimensions["month"][_trade_month(trade)] += profit
        dimensions["symbol"][str(trade.get("symbol") or "UNKNOWN")] += profit
        dimensions["fold"][str(trade.get("fold") or "UNKNOWN")] += profit
    return {
        name: _concentration_record(values, total_positive_profit)
        for name, values in dimensions.items()
    }


def _concentration_record(values, total):
    shares = [
        {
            "group": group,
            "positive_profit": round(profit, 4),
            "share_percent": round(profit / total * 100, 4) if total else None,
        }
        for group, profit in sorted(values.items())
    ]
    return {
        "available": bool(total and shares),
        "total_positive_profit": round(total, 4),
        "maximum_share_percent": max(
            (item["share_percent"] for item in shares if item["share_percent"] is not None),
            default=None,
        ),
        "groups": shares,
    }


def _trade_month(trade):
    value = trade.get("exit_time") or trade.get("entry_time")
    if not value:
        return "UNKNOWN"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "UNKNOWN"
    return parsed.strftime("%Y-%m")


def _confidence_band(trade):
    confidence = float(trade.get("confidence") or 0)
    if confidence >= 80:
        return "80_PLUS"
    if confidence >= 70:
        return "70_79"
    if confidence >= 60:
        return "60_69"
    if confidence >= 50:
        return "50_59"
    return "BELOW_50"


def _numeric_gate(name, actual, threshold, comparison):
    if actual is None:
        return _gate(name, "INSUFFICIENT_EVIDENCE", None, threshold, comparison)
    value = float(actual)
    if comparison == "minimum":
        passed = value >= float(threshold)
    elif comparison == "maximum":
        passed = value <= float(threshold)
    elif comparison == "greater_than":
        passed = value > float(threshold)
    else:
        raise ValueError(f"Unsupported comparison: {comparison}")
    return _gate(name, "PASS" if passed else "FAIL", round(value, 4), threshold, comparison)


def _boolean_gate(name, actual, note=None):
    if actual is None:
        return _gate(name, "INSUFFICIENT_EVIDENCE", None, True, "required", note)
    return _gate(name, "PASS" if actual else "FAIL", bool(actual), True, "required", note)


def _concentration_gate(name, record, thresholds):
    if not record["available"]:
        return _gate(
            name,
            "INSUFFICIENT_EVIDENCE",
            None,
            thresholds.profit_concentration_maximum_percent,
            "maximum",
            "Positive profit is unavailable, so profit-source concentration cannot be measured.",
        )
    return _numeric_gate(
        name,
        record["maximum_share_percent"],
        thresholds.profit_concentration_maximum_percent,
        "maximum",
    )


def _adverse_cost_gate(baseline_result, adverse_result):
    adverse = dict(adverse_result or {})
    adverse_oos = dict(adverse.get("out_of_sample") or {})
    if not adverse_oos:
        return _gate(
            "positive_under_adverse_costs",
            "INSUFFICIENT_EVIDENCE",
            None,
            "positive return and expectancy",
            "required",
            "A separately executed adverse fee/slippage replay is required.",
        )
    configuration_match = _cost_stress_configuration_match(
        baseline_result,
        adverse,
    )
    if configuration_match["status"] != "PASS":
        return _gate(
            "positive_under_adverse_costs",
            "INSUFFICIENT_EVIDENCE",
            configuration_match,
            "identical selections with higher declared costs",
            "required",
            configuration_match["note"],
        )
    total_return = adverse_oos.get("total_return_percent")
    expectancy = adverse_oos.get("expectancy_percent")
    if total_return is None or expectancy is None:
        return _gate(
            "positive_under_adverse_costs",
            "INSUFFICIENT_EVIDENCE",
            {
                "total_return_percent": total_return,
                "expectancy_percent": expectancy,
            },
            "positive return and expectancy",
            "required",
        )
    actual = {
        "total_return_percent": round(float(total_return), 4),
        "expectancy_percent": round(float(expectancy), 4),
    }
    passed = actual["total_return_percent"] > 0 and actual["expectancy_percent"] > 0
    return _gate(
        "positive_under_adverse_costs",
        "PASS" if passed else "FAIL",
        actual,
        "positive return and expectancy",
        "required",
    )


def _cost_stress_configuration_match(baseline, adverse):
    baseline_config = dict((baseline or {}).get("configuration") or {})
    adverse_config = dict((adverse or {}).get("configuration") or {})
    baseline_folds = list((baseline or {}).get("folds") or [])
    adverse_folds = list((adverse or {}).get("folds") or [])
    stable_config_fields = (
        "train_size",
        "test_size",
        "step_size",
        "mode",
        "min_train_trades",
        "stop_grid",
        "target_grid",
        "initial_capital",
        "position_size_percent",
    )
    config_matches = all(
        baseline_config.get(field) == adverse_config.get(field)
        for field in stable_config_fields
    )
    baseline_selections = [
        dict(fold.get("selected_parameters") or {})
        for fold in baseline_folds
    ]
    adverse_selections = [
        dict(fold.get("selected_parameters") or {})
        for fold in adverse_folds
    ]
    selections_match = bool(baseline_selections) and (
        baseline_selections == adverse_selections
    )
    baseline_fee = baseline_config.get("fee_bps")
    baseline_slippage = baseline_config.get("slippage_bps")
    adverse_fee = adverse_config.get("fee_bps")
    adverse_slippage = adverse_config.get("slippage_bps")
    costs_are_adverse = (
        baseline_fee is not None
        and baseline_slippage is not None
        and adverse_fee is not None
        and adverse_slippage is not None
        and float(adverse_fee) >= float(baseline_fee)
        and float(adverse_slippage) >= float(baseline_slippage)
        and (
            float(adverse_fee) > float(baseline_fee)
            or float(adverse_slippage) > float(baseline_slippage)
        )
    )
    passed = config_matches and selections_match and costs_are_adverse
    return {
        "status": "PASS" if passed else "INVALID",
        "stable_configuration_match": config_matches,
        "fold_selections_match": selections_match,
        "costs_are_strictly_more_adverse": costs_are_adverse,
        "baseline_costs": {
            "fee_bps": baseline_fee,
            "slippage_bps": baseline_slippage,
        },
        "adverse_costs": {
            "fee_bps": adverse_fee,
            "slippage_bps": adverse_slippage,
        },
        "note": (
            None
            if passed
            else "Adverse-cost evidence must preserve every non-cost configuration field and each fold's selected parameters."
        ),
    }


def _gate(name, status, actual, threshold, comparison, note=None):
    return {
        "name": name,
        "status": status,
        "actual": actual,
        "threshold": threshold,
        "comparison": comparison,
        "note": note,
    }


def _overall_status(gates):
    statuses = {gate["status"] for gate in gates}
    if "FAIL" in statuses:
        return "FAIL"
    if "INSUFFICIENT_EVIDENCE" in statuses:
        return "INSUFFICIENT_EVIDENCE"
    return "PASS" if gates else "INSUFFICIENT_EVIDENCE"


def _baseline_comparison(current, prior):
    prior_metrics = dict(prior or {})
    if not prior_metrics:
        return {
            "status": "NOT_PROVIDED",
            "note": "Provide the frozen pre-repair baseline metrics for truth-repair impact measurement.",
        }
    fields = (
        "total_return_percent",
        "profit_factor",
        "win_rate",
        "max_drawdown_percent",
        "expectancy_percent",
    )
    return {
        "status": "AVAILABLE",
        "metrics": {
            field: {
                "prior": prior_metrics.get(field),
                "current": current.get(field),
                "delta": _delta(current.get(field), prior_metrics.get(field)),
            }
            for field in fields
        },
    }


def _delta(current, prior):
    if current is None or prior is None:
        return None
    return round(float(current) - float(prior), 4)
