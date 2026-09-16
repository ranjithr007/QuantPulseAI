from dataclasses import asdict, dataclass
from datetime import datetime
import json
from math import sqrt
from statistics import mean, pstdev

from sqlalchemy.exc import SQLAlchemyError

from app.database.models.trade_thesis import TradeThesis
from app.database.models.market_regimes import MarketRegime
from app.paper_trading.exit_evidence import classify_exit
from app.paper_trading.exit_evidence import read_evidence
from app.paper_trading.operational_exit_quality import EXIT_DEADLINE_GRACE_MINUTES
from app.paper_trading.operational_exit_quality import MAX_PROMOTION_EXIT_QUOTE_AGE_SECONDS
from app.paper_trading.operational_exit_quality import is_operationally_contaminated_exit
from app.paper_trading.operational_exit_quality import late_time_exit_delay_minutes
from app.paper_trading.operational_exit_quality import stale_recorded_exit_quote_age_seconds


MEASUREMENT_VERSION = "extended_paper_measurement_v2"


@dataclass(frozen=True)
class MeasurementGates:
    min_closed_trades: int = 100
    min_observation_days: int = 90
    min_profit_factor: float = 1.3
    min_reward_risk: float = 1.5
    min_win_rate_percent: float = 45.0
    min_expectancy_percent: float = 0.0
    min_total_return_percent: float = 0.0
    max_drawdown_percent: float = 20.0
    min_cohort_closed_trades: int = 20

    def __post_init__(self):
        if self.min_closed_trades < 1:
            raise ValueError("min_closed_trades must be at least 1")
        if self.min_observation_days < 1:
            raise ValueError("min_observation_days must be at least 1")
        if self.min_profit_factor <= 0:
            raise ValueError("min_profit_factor must be greater than zero")
        if self.min_reward_risk <= 0:
            raise ValueError("min_reward_risk must be greater than zero")
        if not 0 < self.min_win_rate_percent <= 100:
            raise ValueError("min_win_rate_percent must be between 0 and 100")
        if self.max_drawdown_percent <= 0:
            raise ValueError("max_drawdown_percent must be greater than zero")
        if self.min_cohort_closed_trades < 1:
            raise ValueError("min_cohort_closed_trades must be at least 1")


def build_measurement_report(trades, gates=None, as_of=None):
    gates = gates or MeasurementGates()
    as_of = _as_datetime(as_of) if as_of is not None else datetime.utcnow()
    records = list(trades or [])
    overall = _scorecard(records, as_of)
    evidence_records = [
        trade for trade in records if not is_operationally_contaminated_exit(trade)
    ]
    evidence_overall = _scorecard(evidence_records, as_of)
    excluded_exit_count = len(records) - len(evidence_records)
    evidence_checks = [
        _check(
            "closed_trade_sample",
            evidence_overall["closed_trades"] >= gates.min_closed_trades,
            evidence_overall["closed_trades"],
            gates.min_closed_trades,
            "minimum",
        ),
        _check(
            "observation_period_days",
            evidence_overall["observation_days"] >= gates.min_observation_days,
            evidence_overall["observation_days"],
            gates.min_observation_days,
            "minimum",
        ),
    ]
    performance_checks = [
        _check(
            "positive_net_return",
            evidence_overall["compounded_return_percent"] > gates.min_total_return_percent,
            evidence_overall["compounded_return_percent"],
            gates.min_total_return_percent,
            "greater_than",
        ),
        _check(
            "positive_expectancy",
            evidence_overall["expectancy_percent"] > gates.min_expectancy_percent,
            evidence_overall["expectancy_percent"],
            gates.min_expectancy_percent,
            "greater_than",
        ),
        _check(
            "win_rate",
            evidence_overall["win_rate"] >= gates.min_win_rate_percent,
            evidence_overall["win_rate"],
            gates.min_win_rate_percent,
            "minimum",
        ),
        _check(
            "reward_risk_ratio",
            _reward_risk_passes(evidence_overall, gates.min_reward_risk),
            evidence_overall["payoff_ratio"],
            gates.min_reward_risk,
            "minimum",
        ),
        _check(
            "profit_factor",
            _profit_factor_passes(evidence_overall, gates.min_profit_factor),
            evidence_overall["profit_factor"],
            gates.min_profit_factor,
            "minimum",
        ),
        _check(
            "maximum_drawdown",
            evidence_overall["max_drawdown_percent"] <= gates.max_drawdown_percent,
            evidence_overall["max_drawdown_percent"],
            gates.max_drawdown_percent,
            "maximum",
        ),
    ]
    evidence_sufficient = all(item["passed"] for item in evidence_checks)
    performance_passed = all(item["passed"] for item in performance_checks)

    if not evidence_sufficient:
        status = "INSUFFICIENT_EVIDENCE"
    elif performance_passed:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "measurement_version": MEASUREMENT_VERSION,
        "generated_at": as_of.isoformat(),
        "status": status,
        "policy": {
            "objective": "Reliable positive expectancy after simulated fees and slippage",
            "win_rate_gate": "EVALUATED",
            "reason": "Win rate must be paired with reward/risk, expectancy, drawdown, and profit factor.",
            "roadmap_targets": {
                "min_closed_trades": gates.min_closed_trades,
                "min_observation_days": gates.min_observation_days,
                "min_profit_factor": gates.min_profit_factor,
                "min_reward_risk": gates.min_reward_risk,
                "min_win_rate_percent": gates.min_win_rate_percent,
                "min_expectancy_percent": gates.min_expectancy_percent,
                "min_total_return_percent": gates.min_total_return_percent,
                "max_drawdown_percent": gates.max_drawdown_percent,
            },
        },
        "gates": asdict(gates),
        "evaluation": {
            "scorecard_scope": "CLEAN_OPERATIONAL_EVIDENCE_ONLY",
            "excluded_operationally_contaminated_exits": excluded_exit_count,
            "evidence_sufficient": evidence_sufficient,
            "performance_passed": performance_passed,
            "evidence_checks": evidence_checks,
            "performance_checks": performance_checks,
        },
        "overall": overall,
        "evidence_overall": evidence_overall,
        "confidence_calibration": build_confidence_calibration(
            records,
            gates,
            as_of,
        ),
        "return_decomposition": _return_decomposition(records),
        "cohorts": {
            "strategy": _cohort_scorecards(records, "strategy", gates, as_of),
            "symbol": _cohort_scorecards(records, "symbol", gates, as_of),
            "side": _cohort_scorecards(records, "side", gates, as_of),
            "mode": _cohort_scorecards(records, "mode", gates, as_of),
            "entry_timeframe": _cohort_scorecards(records, "entry_timeframe", gates, as_of),
            "regime": _cohort_scorecards(records, "regime", gates, as_of),
            "exit_classification": _cohort_scorecards(
                records,
                "exit_classification",
                gates,
                as_of,
            ),
            "confidence_band": _cohort_scorecards(
                records,
                "confidence_band",
                gates,
                as_of,
            ),
        },
        "scenario_accuracy": _scenario_accuracy(records),
        "regime_accuracy": _regime_accuracy(records),
        "operational_exit_quality": _operational_exit_quality(records),
        "data_quality": _data_quality(records),
    }


def attach_scenario_context(db, trades):
    """Attach persisted thesis scenario labels without changing paper-trade schema."""
    records = list(trades or [])
    thesis_ids = {
        getattr(trade, "thesis_id", None)
        for trade in records
        if getattr(trade, "thesis_id", None) is not None
    }
    if not thesis_ids:
        return records

    try:
        theses = (
            db.query(TradeThesis)
            .filter(TradeThesis.id.in_(thesis_ids))
            .all()
        )
    except SQLAlchemyError:
        try:
            db.rollback()
        except Exception:
            pass
        return records

    by_id = {thesis.id: thesis for thesis in theses}
    for trade in records:
        thesis = by_id.get(getattr(trade, "thesis_id", None))
        scenario = _decode_json(getattr(thesis, "scenario_json", None)) if thesis else None
        primary = scenario.get("scenario_type") if isinstance(scenario, dict) else None
        try:
            setattr(trade, "scenario", scenario)
            setattr(trade, "scenario_type", primary)
        except Exception:
            # Dict-like test fixtures are handled without requiring a model mutation.
            if isinstance(trade, dict):
                trade["scenario"] = scenario
                trade["scenario_type"] = primary
    return records


def attach_regime_outcome_context(db, trades):
    """Resolve the latest regime at each paper-trade close timestamp."""
    records = list(trades or [])
    for trade in records:
        closed_at = _value(trade, "closed_at")
        symbol = _value(trade, "symbol")
        timeframe = _value(trade, "entry_timeframe")
        if not closed_at or not symbol or not timeframe:
            continue
        try:
            regime = (
                db.query(MarketRegime)
                .filter(MarketRegime.Symbol == symbol)
                .filter(MarketRegime.Timeframe == timeframe)
                .filter(MarketRegime.CreatedAt <= closed_at)
                .order_by(MarketRegime.CreatedAt.desc(), MarketRegime.Id.desc())
                .first()
            )
        except SQLAlchemyError:
            try:
                db.rollback()
            except Exception:
                pass
            return records

        realized = getattr(regime, "Regime", None) if regime is not None else None
        try:
            setattr(trade, "realized_regime", realized)
        except Exception:
            if isinstance(trade, dict):
                trade["realized_regime"] = realized
    return records


def _scorecard(trades, as_of):
    closed = [trade for trade in trades if _value(trade, "status") == "CLOSED"]
    returns = [
        float(value)
        for trade in closed
        if (value := _value(trade, "pnl_percent")) is not None
    ]
    positive = [value for value in returns if value > 0]
    negative = [value for value in returns if value < 0]
    breakeven = [value for value in returns if value == 0]
    gross_profit = sum(positive)
    gross_loss = abs(sum(negative))
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss else None
    average_win = mean(positive) if positive else 0.0
    average_loss = abs(mean(negative)) if negative else 0.0
    payoff_ratio = round(average_win / average_loss, 4) if average_loss else None
    equity, max_drawdown = _equity_and_drawdown(returns)
    observation_days, first_opened_at = _observation_period(trades, as_of)
    total_fees = sum(
        float(_value(trade, "fees_percent") or 0)
        for trade in closed
    )
    total_funding_cost = sum(
        float(_value(trade, "funding_cost_percent") or 0)
        for trade in closed
    )

    return {
        "total_trades": len(trades),
        "open_trades": sum(1 for trade in trades if _value(trade, "status") == "OPEN"),
        "closed_trades": len(closed),
        "measured_closed_trades": len(returns),
        "wins": len(positive),
        "losses": len(negative),
        "breakeven": len(breakeven),
        "win_rate": round((len(positive) / len(returns)) * 100, 2) if returns else 0.0,
        "average_win_percent": round(average_win, 4),
        "average_loss_percent": round(average_loss, 4),
        "payoff_ratio": payoff_ratio,
        "gross_profit_percent": round(gross_profit, 4),
        "gross_loss_percent": round(gross_loss, 4),
        "net_pnl_percent": round(sum(returns), 4),
        "compounded_return_percent": round(equity - 100, 4),
        "expectancy_percent": round(mean(returns), 4) if returns else 0.0,
        "profit_factor": profit_factor,
        "profit_factor_status": (
            "CALCULATED"
            if negative
            else "NO_LOSSES"
            if positive
            else "UNAVAILABLE"
        ),
        "max_drawdown_percent": round(max_drawdown, 4),
        "trade_return_sharpe": _trade_return_sharpe(returns),
        "simulated_fees_percent": round(total_fees, 4),
        "simulated_funding_cost_percent": round(total_funding_cost, 6),
        "observation_days": observation_days,
        "first_opened_at": first_opened_at.isoformat() if first_opened_at else None,
        "as_of": as_of.isoformat(),
    }


def _cohort_scorecards(trades, dimension, gates, as_of):
    grouped = {}
    for trade in trades:
        key = _cohort_value(trade, dimension)
        grouped.setdefault(key, []).append(trade)

    results = []
    for key, cohort_trades in grouped.items():
        scorecard = _scorecard(cohort_trades, as_of)
        results.append(
            {
                "value": key,
                "evidence_status": (
                    "SUFFICIENT"
                    if scorecard["closed_trades"] >= gates.min_cohort_closed_trades
                    else "INSUFFICIENT_EVIDENCE"
                ),
                **scorecard,
            }
        )
    return sorted(results, key=lambda item: (-item["closed_trades"], item["value"]))


def _cohort_value(trade, dimension):
    if dimension == "strategy":
        strategy_id = _value(trade, "strategy_id")
        strategy_version = _value(trade, "strategy_version")
        if strategy_id in (None, ""):
            return "UNKNOWN"
        if strategy_version in (None, ""):
            return str(strategy_id)
        return f"{strategy_id}@{strategy_version}"
    if dimension == "confidence_band":
        confidence = _value(trade, "confidence")
        if confidence is None:
            return "UNKNOWN"
        confidence = float(confidence)
        if confidence < 60:
            return "BELOW_60"
        if confidence < 70:
            return "60_69"
        if confidence < 80:
            return "70_79"
        return "80_PLUS"
    if dimension == "exit_classification":
        recorded = read_evidence(_value(trade, "exit_evidence_json")).get(
            "classification"
        )
        return str(recorded or classify_exit(trade)).upper()
    value = _value(trade, dimension)
    return str(value) if value not in (None, "") else "UNKNOWN"


def build_confidence_calibration(trades, gates=None, as_of=None):
    """Check whether higher recorded confidence separates better outcomes.

    This is a descriptive evidence gate, not a threshold optimizer. The fixed
    60-point split matches the published confidence cohorts and is never chosen
    from the observed outcomes.
    """
    gates = gates or MeasurementGates()
    as_of = _as_datetime(as_of) if as_of is not None else datetime.utcnow()
    records = list(trades or [])
    closed_with_outcomes = [
        trade
        for trade in records
        if _value(trade, "status") == "CLOSED"
        and _value(trade, "confidence") is not None
        and _value(trade, "pnl_percent") is not None
    ]
    measured = [
        trade
        for trade in closed_with_outcomes
        if not is_operationally_contaminated_exit(trade)
    ]
    lower = [trade for trade in measured if float(_value(trade, "confidence")) < 60]
    higher = [trade for trade in measured if float(_value(trade, "confidence")) >= 60]
    lower_score = _scorecard(lower, as_of)
    higher_score = _scorecard(higher, as_of)
    gap = round(
        higher_score["expectancy_percent"] - lower_score["expectancy_percent"],
        4,
    )
    correlation = _pearson_correlation(
        [float(_value(trade, "confidence")) for trade in measured],
        [float(_value(trade, "pnl_percent")) for trade in measured],
    )
    sufficient = bool(
        lower_score["closed_trades"] >= gates.min_cohort_closed_trades
        and higher_score["closed_trades"] >= gates.min_cohort_closed_trades
    )
    aligned = bool(gap > 0 and correlation is not None and correlation > 0)
    higher_has_positive_edge = bool(
        higher_score["expectancy_percent"] > 0
        and higher_score["profit_factor"] is not None
        and higher_score["profit_factor"] > 1
    )
    status = (
        "INSUFFICIENT_EVIDENCE"
        if not sufficient
        else "DIRECTIONALLY_ALIGNED"
        if aligned
        else "NOT_DIRECTIONALLY_ALIGNED"
    )
    direction = (
        "HIGHER_OUTPERFORMS"
        if gap > 0
        else "HIGHER_UNDERPERFORMS"
        if gap < 0
        else "FLAT"
    )
    return {
        "status": status,
        "direction": direction,
        "evidence_scope": "CLEAN_OPERATIONAL_EVIDENCE_ONLY",
        "excluded_operationally_contaminated_exits": (
            len(closed_with_outcomes) - len(measured)
        ),
        "evaluated_trades": len(measured),
        "minimum_trades_per_group": gates.min_cohort_closed_trades,
        "sample_sufficient": sufficient,
        "higher_confidence_positive_edge": higher_has_positive_edge,
        "higher_confidence_promotion_eligible": bool(
            sufficient and aligned and higher_has_positive_edge
        ),
        "expectancy_gap_percentage_points": gap,
        "confidence_pnl_correlation": correlation,
        "below_60": {
            "closed_trades": lower_score["closed_trades"],
            "win_rate": lower_score["win_rate"],
            "expectancy_percent": lower_score["expectancy_percent"],
            "profit_factor": lower_score["profit_factor"],
        },
        "at_least_60": {
            "closed_trades": higher_score["closed_trades"],
            "win_rate": higher_score["win_rate"],
            "expectancy_percent": higher_score["expectancy_percent"],
            "profit_factor": higher_score["profit_factor"],
        },
        "note": (
            "Fixed predeclared confidence groups; descriptive association only. "
            "This report does not tune an entry threshold or prove causation."
        ),
    }


def _pearson_correlation(left, right):
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left)
    right_variance = sum((value - right_mean) ** 2 for value in right)
    denominator = sqrt(left_variance * right_variance)
    return round(numerator / denominator, 4) if denominator else None


def _return_decomposition(trades):
    """Reconcile persisted post-fill price return to the official net return."""
    closed = [trade for trade in trades if _value(trade, "status") == "CLOSED"]
    required = (
        "gross_pnl_percent",
        "fees_percent",
        "funding_cost_percent",
        "pnl_percent",
    )
    complete = [
        trade
        for trade in closed
        if all(_value(trade, field) is not None for field in required)
    ]
    post_fill_gross = sum(
        float(_value(trade, "gross_pnl_percent")) for trade in complete
    )
    fees = sum(float(_value(trade, "fees_percent")) for trade in complete)
    funding = sum(
        float(_value(trade, "funding_cost_percent")) for trade in complete
    )
    net = sum(float(_value(trade, "pnl_percent")) for trade in complete)
    total_cost = fees + funding
    reconciled_net = post_fill_gross - total_cost
    error = net - reconciled_net
    cost_share = (
        round((total_cost / abs(net)) * 100, 2)
        if net < 0 and total_cost > 0
        else 0.0
    )
    return {
        "status": "COMPLETE" if len(complete) == len(closed) else "INCOMPLETE",
        "closed_trades": len(closed),
        "reconciled_trades": len(complete),
        "missing_component_trades": len(closed) - len(complete),
        "post_fill_gross_return_percent": round(post_fill_gross, 4),
        "fees_percent": round(fees, 4),
        "funding_cost_percent": round(funding, 6),
        "total_cost_drag_percent": round(total_cost, 4),
        "net_return_percent": round(net, 4),
        "reconciliation_error_percent": round(error, 6),
        "cost_share_of_net_loss_percent": cost_share,
        "pre_cost_result": (
            "POSITIVE" if post_fill_gross > 0 else "NEGATIVE" if post_fill_gross < 0 else "FLAT"
        ),
        "costs_changed_result_sign": bool(
            (post_fill_gross > 0 and net <= 0) or (post_fill_gross < 0 and net >= 0)
        ),
        "slippage_policy": (
            "Entry and exit slippage are already embedded in the simulated fill "
            "prices and therefore in post-fill gross return."
        ),
    }


def _scenario_accuracy(trades):
    evaluated = []
    for trade in trades:
        scenario_type = _value(trade, "scenario_type")
        pnl_percent = _value(trade, "pnl_percent")
        if not scenario_type or pnl_percent is None:
            continue

        expected_side = {
            "BULLISH_CONTINUATION": "LONG",
            "BEARISH_CONTINUATION": "SHORT",
        }.get(str(scenario_type).upper())
        side = str(_value(trade, "side") or "").upper()
        # A directional scenario is correct only when the candidate side agrees
        # and the closed trade made a positive net return. Non-directional
        # scenarios should not have produced an entry and therefore count as
        # incorrect if a paper trade was opened from them.
        correct = bool(expected_side and side == expected_side and float(pnl_percent) > 0)
        evaluated.append(
            {
                "scenario_type": str(scenario_type),
                "side": side or None,
                "correct": correct,
                "pnl_percent": round(float(pnl_percent), 4),
            }
        )

    grouped = {}
    for item in evaluated:
        grouped.setdefault(item["scenario_type"], []).append(item)

    by_scenario = []
    for scenario_type, items in sorted(grouped.items()):
        correct = sum(1 for item in items if item["correct"])
        by_scenario.append(
            {
                "scenario_type": scenario_type,
                "evaluated_trades": len(items),
                "correct": correct,
                "incorrect": len(items) - correct,
                "accuracy_percent": round((correct / len(items)) * 100, 4),
            }
        )

    return {
        "status": "CALCULATED" if evaluated else "NOT_STARTED",
        "evaluated_trades": len(evaluated),
        "correct": sum(1 for item in evaluated if item["correct"]),
        "incorrect": sum(1 for item in evaluated if not item["correct"]),
        "accuracy_percent": (
            round((sum(1 for item in evaluated if item["correct"]) / len(evaluated)) * 100, 4)
            if evaluated
            else None
        ),
        "by_scenario": by_scenario,
        "note": (
            "Accuracy uses persisted primary scenario labels and closed net PnL."
            if evaluated
            else "No closed paper trades contain a persisted scenario label."
        ),
    }


def _regime_accuracy(trades):
    evaluated = []
    for trade in trades:
        predicted = _value(trade, "regime")
        realized = _value(trade, "realized_regime")
        if not predicted or not realized:
            continue
        predicted = str(predicted)
        realized = str(realized)
        evaluated.append(
            {
                "predicted_regime": predicted,
                "realized_regime": realized,
                "correct": predicted == realized,
            }
        )

    pairs = {}
    for item in evaluated:
        key = (item["predicted_regime"], item["realized_regime"])
        pairs[key] = pairs.get(key, 0) + 1

    return {
        "status": "CALCULATED" if evaluated else "NOT_STARTED",
        "evaluated_trades": len(evaluated),
        "correct": sum(1 for item in evaluated if item["correct"]),
        "incorrect": sum(1 for item in evaluated if not item["correct"]),
        "accuracy_percent": (
            round((sum(1 for item in evaluated if item["correct"]) / len(evaluated)) * 100, 4)
            if evaluated
            else None
        ),
        "confusion_pairs": [
            {
                "predicted_regime": predicted,
                "realized_regime": realized,
                "count": count,
            }
            for (predicted, realized), count in sorted(pairs.items())
        ],
        "note": (
            "Accuracy compares the entry regime with the latest persisted regime at close."
            if evaluated
            else "No closed paper trades have a persisted regime observation at close."
        ),
    }


def _equity_and_drawdown(returns):
    equity = 100.0
    peak = equity
    max_drawdown = 0.0
    for trade_return in returns:
        equity *= 1 + (trade_return / 100)
        peak = max(peak, equity)
        drawdown = ((peak - equity) / peak) * 100 if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
    return equity, max_drawdown


def _trade_return_sharpe(returns):
    if len(returns) < 2:
        return 0.0
    deviation = pstdev(returns)
    if deviation == 0:
        return 0.0
    return round((mean(returns) / deviation) * sqrt(len(returns)), 4)


def _observation_period(trades, as_of):
    timestamps = [
        timestamp
        for trade in trades
        if (timestamp := _as_datetime(_value(trade, "opened_at") or _value(trade, "created_at")))
    ]
    if not timestamps:
        return 0, None
    first_opened_at = min(timestamps)
    elapsed = as_of - first_opened_at
    return max(0, elapsed.days), first_opened_at


def _data_quality(trades):
    closed = [trade for trade in trades if _value(trade, "status") == "CLOSED"]
    context_fields = ("mode", "entry_timeframe", "regime")
    return {
        "closed_trades_missing_net_pnl": sum(
            1 for trade in closed if _value(trade, "pnl_percent") is None
        ),
        "closed_trades_missing_fee_snapshot": sum(
            1 for trade in closed if _value(trade, "fees_percent") is None
        ),
        "trades_missing_context": {
            field: sum(1 for trade in trades if _value(trade, field) in (None, ""))
            for field in context_fields
        },
        "trades_missing_pipeline_lineage": sum(
            1
            for trade in trades
            if _value(trade, "data_generation_id") in (None, "")
        ),
        "trades_missing_validation_contract": sum(
            1
            for trade in trades
            if _value(trade, "validation_contract_version") in (None, "")
        ),
        "trades_missing_fill_model": sum(
            1
            for trade in trades
            if _value(trade, "fill_model_version") in (None, "")
        ),
        "trades_missing_entry_slippage_snapshot": sum(
            1
            for trade in trades
            if _value(trade, "entry_slippage_percent") is None
        ),
        "closed_trades_missing_exit_slippage_snapshot": sum(
            1
            for trade in closed
            if _value(trade, "exit_slippage_percent") is None
        ),
        "closed_trades_missing_trailing_activation": sum(
            1
            for trade in closed
            if _value(trade, "trailing_activation_r") is None
        ),
        "trades_missing_funding_snapshot": sum(
            1
            for trade in trades
            if _value(trade, "funding_rate_snapshot") is None
        ),
        "closed_trades_missing_funding_accrual": sum(
            1
            for trade in closed
            if _value(trade, "funding_cost_percent") is None
            or _value(trade, "funding_event_count") is None
        ),
        "trades_missing_open_interest_snapshot": sum(
            1
            for trade in trades
            if _value(trade, "open_interest_snapshot") is None
        ),
        "legacy_trade_note": (
            "Trades opened before measurement v1 may not contain fee or context snapshots."
        ),
    }


def _operational_exit_quality(trades):
    """Expose infrastructure-tainted exits without changing account P&L."""

    closed = [trade for trade in trades if _value(trade, "status") == "CLOSED"]
    time_exits = [
        trade
        for trade in closed
        if str(_value(trade, "exit_reason") or "").upper() == "TIME_EXIT"
    ]
    late = []
    for trade in time_exits:
        delay_minutes = late_time_exit_delay_minutes(trade)
        if delay_minutes is not None:
            late.append((trade, delay_minutes))

    observed_only = 0
    missing_evidence = 0
    stale_recorded_exits = []
    for trade in closed:
        evidence = _decode_json(_value(trade, "exit_evidence_json"))
        if evidence is None:
            missing_evidence += 1
            continue
        coverage = str((evidence.get("observations") or {}).get("coverage") or "")
        if coverage.upper() == "OBSERVED_ONLY":
            observed_only += 1
        stale_age = stale_recorded_exit_quote_age_seconds(trade)
        if stale_age is not None:
            stale_recorded_exits.append((trade, stale_age))

    by_strategy = {}
    for trade, delay_minutes in late:
        strategy = _cohort_value(trade, "strategy")
        group = by_strategy.setdefault(
            strategy,
            {
                "strategy": strategy,
                "late_time_exits": 0,
                "net_pnl_percent": 0.0,
                "max_delay_minutes": 0.0,
            },
        )
        group["late_time_exits"] += 1
        group["net_pnl_percent"] += float(_value(trade, "pnl_percent") or 0)
        group["max_delay_minutes"] = max(
            group["max_delay_minutes"],
            delay_minutes,
        )

    late_pnl = sum(float(_value(trade, "pnl_percent") or 0) for trade, _ in late)
    return {
        "status": "DEGRADED" if late or stale_recorded_exits else "OK",
        "deadline_grace_minutes": EXIT_DEADLINE_GRACE_MINUTES,
        "closed_trades": len(closed),
        "time_exits": len(time_exits),
        "late_time_exits": len(late),
        "late_time_exit_net_pnl_percent": round(late_pnl, 4),
        "maximum_exit_delay_minutes": round(
            max((delay for _, delay in late), default=0.0),
            2,
        ),
        "maximum_promotion_quote_age_seconds": MAX_PROMOTION_EXIT_QUOTE_AGE_SECONDS,
        "stale_recorded_exit_triggers": len(stale_recorded_exits),
        "maximum_recorded_trigger_quote_age_seconds": round(
            max((age for _, age in stale_recorded_exits), default=0.0),
            3,
        ),
        "observed_only_exit_evidence": observed_only,
        "closed_trades_missing_exit_evidence": missing_evidence,
        "late_time_exits_by_strategy": [
            {
                **item,
                "net_pnl_percent": round(item["net_pnl_percent"], 4),
                "max_delay_minutes": round(item["max_delay_minutes"], 2),
            }
            for item in sorted(
                by_strategy.values(),
                key=lambda value: (-value["late_time_exits"], value["strategy"]),
            )
        ],
        "accounting_policy": (
            "Late exits remain included in account P&L and headline strategy "
            "results, but are excluded from validation and promotion scorecards."
        ),
    }


def _profit_factor_passes(scorecard, threshold):
    if scorecard["gross_loss_percent"] == 0:
        return scorecard["gross_profit_percent"] > 0
    return scorecard["profit_factor"] >= threshold


def _reward_risk_passes(scorecard, threshold):
    payoff_ratio = scorecard.get("payoff_ratio")
    if payoff_ratio is None:
        gross_loss = float(scorecard.get("gross_loss_percent") or 0)
        gross_profit = float(scorecard.get("gross_profit_percent") or 0)
        return gross_loss == 0 and gross_profit > 0
    return float(payoff_ratio) >= threshold


def _check(name, passed, actual, threshold, comparison):
    return {
        "name": name,
        "passed": bool(passed),
        "actual": actual,
        "threshold": threshold,
        "comparison": comparison,
    }


def _value(item, name):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _decode_json(value):
    if isinstance(value, dict):
        return value
    if not value:
        return None
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else None
    except (TypeError, ValueError):
        return None


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
