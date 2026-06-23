from dataclasses import asdict, dataclass
from datetime import datetime
from math import sqrt
from statistics import mean, pstdev


MEASUREMENT_VERSION = "extended_paper_measurement_v1"


@dataclass(frozen=True)
class MeasurementGates:
    min_closed_trades: int = 100
    min_observation_days: int = 56
    min_profit_factor: float = 1.25
    min_expectancy_percent: float = 0.0
    min_total_return_percent: float = 0.0
    max_drawdown_percent: float = 15.0
    min_cohort_closed_trades: int = 20

    def __post_init__(self):
        if self.min_closed_trades < 1:
            raise ValueError("min_closed_trades must be at least 1")
        if self.min_observation_days < 1:
            raise ValueError("min_observation_days must be at least 1")
        if self.min_profit_factor <= 0:
            raise ValueError("min_profit_factor must be greater than zero")
        if self.max_drawdown_percent <= 0:
            raise ValueError("max_drawdown_percent must be greater than zero")
        if self.min_cohort_closed_trades < 1:
            raise ValueError("min_cohort_closed_trades must be at least 1")


def build_measurement_report(trades, gates=None, as_of=None):
    gates = gates or MeasurementGates()
    as_of = _as_datetime(as_of) if as_of is not None else datetime.utcnow()
    records = list(trades or [])
    overall = _scorecard(records, as_of)
    evidence_checks = [
        _check(
            "closed_trade_sample",
            overall["closed_trades"] >= gates.min_closed_trades,
            overall["closed_trades"],
            gates.min_closed_trades,
            "minimum",
        ),
        _check(
            "observation_period_days",
            overall["observation_days"] >= gates.min_observation_days,
            overall["observation_days"],
            gates.min_observation_days,
            "minimum",
        ),
    ]
    performance_checks = [
        _check(
            "positive_net_return",
            overall["compounded_return_percent"] > gates.min_total_return_percent,
            overall["compounded_return_percent"],
            gates.min_total_return_percent,
            "greater_than",
        ),
        _check(
            "positive_expectancy",
            overall["expectancy_percent"] > gates.min_expectancy_percent,
            overall["expectancy_percent"],
            gates.min_expectancy_percent,
            "greater_than",
        ),
        _check(
            "profit_factor",
            _profit_factor_passes(overall, gates.min_profit_factor),
            overall["profit_factor"],
            gates.min_profit_factor,
            "minimum",
        ),
        _check(
            "maximum_drawdown",
            overall["max_drawdown_percent"] <= gates.max_drawdown_percent,
            overall["max_drawdown_percent"],
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
            "win_rate_gate": "NOT_USED",
            "reason": "Win count alone does not determine profitability.",
        },
        "gates": asdict(gates),
        "evaluation": {
            "evidence_sufficient": evidence_sufficient,
            "performance_passed": performance_passed,
            "evidence_checks": evidence_checks,
            "performance_checks": performance_checks,
        },
        "overall": overall,
        "cohorts": {
            "symbol": _cohort_scorecards(records, "symbol", gates, as_of),
            "side": _cohort_scorecards(records, "side", gates, as_of),
            "mode": _cohort_scorecards(records, "mode", gates, as_of),
            "entry_timeframe": _cohort_scorecards(records, "entry_timeframe", gates, as_of),
            "regime": _cohort_scorecards(records, "regime", gates, as_of),
            "confidence_band": _cohort_scorecards(
                records,
                "confidence_band",
                gates,
                as_of,
            ),
        },
        "data_quality": _data_quality(records),
    }


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
    value = _value(trade, dimension)
    return str(value) if value not in (None, "") else "UNKNOWN"


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
        "legacy_trade_note": (
            "Trades opened before measurement v1 may not contain fee or context snapshots."
        ),
    }


def _profit_factor_passes(scorecard, threshold):
    if scorecard["gross_loss_percent"] == 0:
        return scorecard["gross_profit_percent"] > 0
    return scorecard["profit_factor"] >= threshold


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


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
