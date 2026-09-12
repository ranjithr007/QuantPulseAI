"""Read-only entry-quality diagnostics over one frozen exit-policy control.

The report groups only information recorded at entry. Future candle excursions
are used to diagnose timing, never to construct a candidate entry filter.
"""

import json
import math
from collections import Counter, defaultdict


CURRENT_EXIT_CONTROL_SPECS = {
    "RECORDED_CURRENT_EXIT": {
        "trailing_activation_r": 0.0,
        "protection_activation_percent": 1.0,
        "disable_one_for_one_trailing": False,
        "use_recorded_trailing_activation": True,
    }
}
MINIMUM_COHORT_TRADES = 30


def _number(value):
    try:
        if isinstance(value, bool):
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _evidence(value):
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(value or "{}")
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, ValueError, UnicodeDecodeError):
        return {}


def _band(value, boundaries, *, missing="NOT_RECORDED"):
    number = _number(value)
    if number is None:
        return missing
    for upper, label in boundaries:
        if number <= upper:
            return label
    return boundaries[-1][1].replace("<=", ">") if boundaries else str(number)


def _confidence_band(value):
    number = _number(value)
    if number is None:
        return "NOT_RECORDED"
    magnitude = abs(number)
    if magnitude < 40:
        return "BELOW_40"
    if magnitude < 50:
        return "40_TO_49_99"
    if magnitude < 60:
        return "50_TO_59_99"
    if magnitude < 70:
        return "60_TO_69_99"
    return "70_PLUS"


def _stop_band(record):
    entry = _number(getattr(record, "entry_price", None))
    stop = _number(getattr(record, "initial_stop_loss", None))
    if entry is None or stop is None or entry <= 0:
        return "NOT_RECORDED", None
    percent = abs(entry - stop) / entry * 100
    if percent <= 0.75 + 1e-9:
        label = "LE_0_75_PERCENT"
    elif percent <= 1.0 + 1e-9:
        label = "0_75_TO_1_PERCENT"
    elif percent <= 1.5 + 1e-9:
        label = "1_TO_1_5_PERCENT"
    else:
        label = "GT_1_5_PERCENT"
    return label, percent


def _slippage_band(value):
    number = _number(value)
    if number is None:
        return "NOT_RECORDED"
    if number <= 0:
        return "PRICE_IMPROVEMENT_OR_FLAT"
    if number <= 0.05:
        return "LE_0_05_PERCENT"
    if number <= 0.10:
        return "0_05_TO_0_10_PERCENT"
    return "GT_0_10_PERCENT"


def _quality_status(evidence):
    passed = evidence.get("entry_quality_passed")
    if passed is True:
        return "PASS"
    if passed is False:
        return "FAIL"
    return "NOT_RECORDED"


def _mean(values):
    selected = [number for value in values if (number := _number(value)) is not None]
    return sum(selected) / len(selected) if selected else None


def _percentage(numerator, denominator):
    return 100 * numerator / denominator if denominator else None


def _metrics(rows):
    before = [row["return_before_funding_percent"] for row in rows]
    after = [
        row["return_after_funding_percent"]
        for row in rows
        if row["return_after_funding_percent"] is not None
    ]
    wins = sum(value for value in after if value > 0)
    losses = -sum(value for value in after if value < 0)
    race_025 = Counter(row["first_0_25r_excursion"] for row in rows)
    race_05 = Counter(row["first_0_5r_excursion"] for row in rows)
    resolved_025 = race_025["FAVOURABLE_FIRST"] + race_025["ADVERSE_FIRST"]
    resolved_05 = race_05["FAVOURABLE_FIRST"] + race_05["ADVERSE_FIRST"]
    return {
        "trades": len(rows),
        "minimum_sample_reached": len(rows) >= MINIMUM_COHORT_TRADES,
        "funding_complete_trades": len(after),
        "win_rate_after_funding_percent": _percentage(
            sum(value > 0 for value in after), len(after)
        ),
        "average_return_before_funding_percent": _mean(before),
        "average_return_after_funding_percent": _mean(after),
        "profit_factor_after_funding": wins / losses if losses else None,
        "target1_hits": sum(row["target1_hit"] for row in rows),
        "pre_t1_losing_stops": sum(row["pre_t1_losing_stop"] for row in rows),
        "average_initial_stop_percent": _mean(
            row["initial_stop_percent"] for row in rows
        ),
        "average_signal_gross_return_percent": _mean(
            row["signal_gross_return_percent"] for row in rows
        ),
        "average_post_fill_gross_return_percent": _mean(
            row["post_fill_gross_return_percent"] for row in rows
        ),
        "average_entry_slippage_cost_percent": _mean(
            row["entry_slippage_cost_percent"] for row in rows
        ),
        "average_exit_slippage_cost_percent": _mean(
            row["exit_slippage_cost_percent"] for row in rows
        ),
        "average_fee_cost_percent": _mean(row["fee_cost_percent"] for row in rows),
        "average_funding_cost_percent": _mean(
            row["funding_cost_percent"] for row in rows
        ),
        "average_full_horizon_mfe_r": _mean(row["mfe_r"] for row in rows),
        "average_full_horizon_mae_r": _mean(row["mae_r"] for row in rows),
        "first_0_25r_excursion_counts": dict(sorted(race_025.items())),
        "adverse_first_0_25r_percent_of_resolved": _percentage(
            race_025["ADVERSE_FIRST"], resolved_025
        ),
        "first_0_5r_excursion_counts": dict(sorted(race_05.items())),
        "adverse_first_0_5r_percent_of_resolved": _percentage(
            race_05["ADVERSE_FIRST"], resolved_05
        ),
    }


def _group(rows, field):
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row.get(field) or "NOT_RECORDED")].append(row)
    return [
        {"cohort": name, **_metrics(values)}
        for name, values in sorted(grouped.items())
    ]


def build_entry_quality_report(base_report, records):
    """Convert a one-policy replay into a non-causal entry diagnostic report."""
    if set((base_report.get("assumptions") or {}).get("policy_specs") or {}) != {
        "RECORDED_CURRENT_EXIT"
    }:
        raise ValueError("entry_quality_requires_single_current_exit_control")

    records_by_id = {record.id: record for record in records}
    rows = []
    coverage = Counter()
    for replay in base_report.get("trades") or []:
        record = records_by_id.get(replay["trade_id"])
        if record is None:
            raise ValueError("entry_quality_record_lineage_missing")
        outcome = replay["outcomes"]["RECORDED_CURRENT_EXIT"]
        costs = outcome["cost_decomposition"]
        path = outcome["full_horizon_excursions"]
        evidence = _evidence(getattr(record, "execution_evidence_json", None))
        stop_band, stop_percent = _stop_band(record)
        profile = str(evidence.get("entry_quality_profile") or "NOT_RECORDED")
        quality_status = _quality_status(evidence)
        drift_atr = _number(evidence.get("entry_drift_atr"))
        mark_age = _number(evidence.get("execution_mark_age_seconds"))
        entry_slippage = costs.get("entry_slippage_cost_percent")
        coverage.update(
            confidence=int(_number(getattr(record, "confidence", None)) is not None),
            entry_timeframe=int(bool(getattr(record, "entry_timeframe", None))),
            regime=int(bool(getattr(record, "regime", None))),
            risk_reward=int(_number(getattr(record, "risk_reward", None)) is not None),
            execution_evidence=int(bool(evidence)),
            entry_quality_result=int(quality_status != "NOT_RECORDED"),
            entry_drift_atr=int(drift_atr is not None),
            execution_mark_age=int(mark_age is not None),
            planned_entry=int(costs.get("planned_entry_available") is True),
        )
        rows.append({
            "trade_id": replay["trade_id"],
            "symbol": replay["symbol"],
            "side": replay["side"],
            "strategy_id": replay["strategy_id"],
            "strategy_version": replay["strategy_version"],
            "strategy_version_cohort": (
                f'{replay["strategy_id"]}|{replay["strategy_version"]}'
            ),
            "entry_timeframe": getattr(record, "entry_timeframe", None),
            "regime": getattr(record, "regime", None),
            "confidence": _number(getattr(record, "confidence", None)),
            "confidence_band": _confidence_band(getattr(record, "confidence", None)),
            "risk_reward": _number(getattr(record, "risk_reward", None)),
            "risk_reward_band": _band(
                getattr(record, "risk_reward", None),
                ((1.49, "LT_1_5"), (1.99, "1_5_TO_1_99"),
                 (2.49, "2_TO_2_49"), (float("inf"), "2_5_PLUS")),
            ),
            "initial_stop_percent": stop_percent,
            "initial_stop_band": stop_band,
            "entry_quality_profile": profile,
            "entry_quality_status": quality_status,
            "entry_setup_type": evidence.get("setup_type") or "NOT_RECORDED",
            "price_structure": evidence.get("price_structure") or "NOT_RECORDED",
            "entry_drift_atr": drift_atr,
            "entry_drift_atr_band": _band(
                drift_atr,
                ((0.25, "LE_0_25R"), (0.5, "0_25_TO_0_5R"),
                 (1.0, "0_5_TO_1R"), (float("inf"), "GT_1R")),
            ),
            "execution_mark_age_seconds": mark_age,
            "execution_mark_age_band": _band(
                mark_age,
                ((15, "LE_15_SECONDS"), (30, "15_TO_30_SECONDS"),
                 (60, "30_TO_60_SECONDS"), (float("inf"), "GT_60_SECONDS")),
            ),
            "entry_slippage_cost_percent": entry_slippage,
            "entry_slippage_band": _slippage_band(entry_slippage),
            "return_before_funding_percent": outcome["return_before_funding_percent"],
            "return_after_funding_percent": outcome["return_after_funding_percent"],
            "target1_hit": outcome["target1_hit"],
            "pre_t1_losing_stop": (
                outcome["events"][-1]["reason"] == "STOP_BEFORE_T1"
                and outcome["pnl_before_funding_inr"] < 0
            ),
            "signal_gross_return_percent": costs.get("signal_gross_return_percent"),
            "post_fill_gross_return_percent": costs["post_fill_gross_return_percent"],
            "exit_slippage_cost_percent": costs["exit_slippage_cost_percent"],
            "fee_cost_percent": costs["fee_cost_percent"],
            "funding_cost_percent": costs["funding_cost_percent"],
            "mfe_r": path["mfe_r"],
            "mae_r": path["mae_r"],
            "first_0_25r_excursion": path["first_0_25r_excursion"],
            "first_0_5r_excursion": path["first_0_5r_excursion"],
        })

    dimensions = (
        "strategy_version_cohort", "symbol", "side", "entry_timeframe", "regime",
        "confidence_band", "risk_reward_band", "initial_stop_band",
        "entry_quality_profile", "entry_quality_status", "entry_setup_type",
        "price_structure", "entry_drift_atr_band", "execution_mark_age_band",
        "entry_slippage_band",
    )
    result = dict(base_report)
    result.update(
        engine="matched_entry_quality_v2e",
        promotion_allowed=False,
        control_policy="RECORDED_CURRENT_EXIT",
        minimum_cohort_trades=MINIMUM_COHORT_TRADES,
        entry_evidence_coverage={
            "paired_trades": len(rows),
            **{key: coverage[key] for key in sorted(coverage)},
        },
        overall_entry_quality=_metrics(rows) if rows else {},
        entry_cohorts={dimension: _group(rows, dimension) for dimension in dimensions},
        limitations=list(base_report.get("limitations") or []) + [
            "Entry cohorts are associations, not causal filters; strategy and market-regime mix may confound them.",
            "Future MFE/MAE and excursion ordering diagnose entry timing only and are never available to the executor at entry.",
            "A same-five-minute-bar adverse/favourable race is explicitly ambiguous because tick ordering is unavailable.",
            "Missing historical execution evidence remains NOT_RECORDED and is never treated as a failed gate.",
            "No cohort may automatically change a strategy, entry gate, paper order, or live policy.",
        ],
        trades=rows,
    )
    # The generic replay summaries would repeat one exit control and can be
    # mistaken for an exit-policy comparison. V2E exposes entry cohorts instead.
    result.pop("summary", None)
    return result
