from dataclasses import asdict, dataclass
from datetime import datetime


ARCHITECTURE_VALIDATION_VERSION = "architecture_paper_gate_v1"


@dataclass(frozen=True)
class PaperValidationPolicy:
    min_closed_trades: int = 100
    min_observation_days: int = 90
    min_profit_factor: float = 1.3
    min_reward_risk: float = 1.5
    min_win_rate_percent: float = 45.0
    min_expectancy_percent: float = 0.0
    min_total_return_percent: float = 0.0
    max_drawdown_percent: float = 20.0

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


DEFAULT_PAPER_VALIDATION_POLICY = PaperValidationPolicy()


def build_architecture_paper_gate(report, policy=None, as_of=None):
    policy = policy or DEFAULT_PAPER_VALIDATION_POLICY
    as_of = _as_datetime(as_of) if as_of is not None else _as_datetime(
        report.get("generated_at") if isinstance(report, dict) else None
    ) or datetime.utcnow()
    overall = dict((report or {}).get("overall") or {})

    checks = [
        _check(
            "closed_trade_sample",
            overall.get("closed_trades", 0) >= policy.min_closed_trades,
            overall.get("closed_trades", 0),
            policy.min_closed_trades,
            "minimum",
        ),
        _check(
            "observation_period_days",
            overall.get("observation_days", 0) >= policy.min_observation_days,
            overall.get("observation_days", 0),
            policy.min_observation_days,
            "minimum",
        ),
        _check(
            "profit_factor",
            _profit_factor_passes(overall, policy.min_profit_factor),
            overall.get("profit_factor"),
            policy.min_profit_factor,
            "minimum",
        ),
        _check(
            "reward_risk_ratio",
            _reward_risk_passes(overall, policy.min_reward_risk),
            overall.get("payoff_ratio"),
            policy.min_reward_risk,
            "minimum",
        ),
        _check(
            "win_rate",
            overall.get("win_rate", 0) >= policy.min_win_rate_percent,
            overall.get("win_rate", 0),
            policy.min_win_rate_percent,
            "minimum",
        ),
        _check(
            "positive_expectancy",
            overall.get("expectancy_percent", 0) > policy.min_expectancy_percent,
            overall.get("expectancy_percent", 0),
            policy.min_expectancy_percent,
            "greater_than",
        ),
        _check(
            "positive_total_return",
            overall.get("compounded_return_percent", 0) > policy.min_total_return_percent,
            overall.get("compounded_return_percent", 0),
            policy.min_total_return_percent,
            "greater_than",
        ),
        _check(
            "maximum_drawdown",
            overall.get("max_drawdown_percent", 100) <= policy.max_drawdown_percent,
            overall.get("max_drawdown_percent", 100),
            policy.max_drawdown_percent,
            "maximum",
        ),
    ]

    evidence_sufficient = all(item["passed"] for item in checks[:2])
    performance_passed = all(item["passed"] for item in checks[2:])

    if not evidence_sufficient:
        status = "INSUFFICIENT_EVIDENCE"
    elif performance_passed:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "validation_version": ARCHITECTURE_VALIDATION_VERSION,
        "generated_at": as_of.isoformat(),
        "status": status,
        "policy": asdict(policy),
        "evaluation": {
            "evidence_sufficient": evidence_sufficient,
            "performance_passed": performance_passed,
            "checks": checks,
        },
        "overall": overall,
    }


def _profit_factor_passes(overall, threshold):
    gross_loss = float(overall.get("gross_loss_percent") or 0)
    if gross_loss == 0:
        return float(overall.get("gross_profit_percent") or 0) > 0

    profit_factor = overall.get("profit_factor")
    return profit_factor is not None and float(profit_factor) >= threshold


def _reward_risk_passes(overall, threshold):
    payoff_ratio = overall.get("payoff_ratio")
    if payoff_ratio is None:
        gross_loss = float(overall.get("gross_loss_percent") or 0)
        gross_profit = float(overall.get("gross_profit_percent") or 0)
        if gross_loss == 0:
            return gross_profit > 0
        return False

    return float(payoff_ratio) >= threshold


def _check(name, passed, actual, threshold, comparison):
    return {
        "name": name,
        "passed": bool(passed),
        "actual": actual,
        "threshold": threshold,
        "comparison": comparison,
    }


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
