from dataclasses import asdict, dataclass
from datetime import datetime
import json
from math import sqrt
from statistics import mean, pstdev

from sqlalchemy.exc import SQLAlchemyError

from app.database.models.trade_thesis import TradeThesis
from app.database.models.market_regimes import MarketRegime


MEASUREMENT_VERSION = "extended_paper_measurement_v1"


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
            "win_rate",
            overall["win_rate"] >= gates.min_win_rate_percent,
            overall["win_rate"],
            gates.min_win_rate_percent,
            "minimum",
        ),
        _check(
            "reward_risk_ratio",
            _reward_risk_passes(overall, gates.min_reward_risk),
            overall["payoff_ratio"],
            gates.min_reward_risk,
            "minimum",
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
        "scenario_accuracy": _scenario_accuracy(records),
        "regime_accuracy": _regime_accuracy(records),
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
