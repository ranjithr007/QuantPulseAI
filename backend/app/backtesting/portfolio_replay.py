from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.backtesting.performance_engine import calculate_performance
from app.utils.freshness import normalize_timestamp_to_utc


PORTFOLIO_REPLAY_VERSION = "portfolio_replay_v1"


@dataclass(frozen=True)
class PortfolioReplayConfig:
    initial_capital: float = 10_000
    max_open_positions: int = 5
    max_gross_exposure_percent: float = 300
    max_cluster_exposure_percent: float = 150

    def __post_init__(self):
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be greater than zero")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be at least 1")
        if self.max_gross_exposure_percent <= 0:
            raise ValueError("max_gross_exposure_percent must be greater than zero")
        if self.max_cluster_exposure_percent <= 0:
            raise ValueError("max_cluster_exposure_percent must be greater than zero")


def build_portfolio_replay(
    symbol_results,
    *,
    initial_capital=10_000,
    max_open_positions=5,
    max_gross_exposure_percent=300,
    max_cluster_exposure_percent=150,
    symbol_clusters=None,
    initial_positions=None,
):
    config = PortfolioReplayConfig(
        initial_capital=float(initial_capital),
        max_open_positions=int(max_open_positions),
        max_gross_exposure_percent=float(max_gross_exposure_percent),
        max_cluster_exposure_percent=float(max_cluster_exposure_percent),
    )
    clusters = {
        str(symbol).upper(): str(cluster)
        for symbol, cluster in dict(symbol_clusters or {}).items()
    }
    candidates = _candidate_trades(symbol_results, clusters)
    active = _initial_active_positions(initial_positions, clusters)
    accepted = []
    rejected = []
    rejection_counts = Counter()

    for candidate in candidates:
        entry_time = candidate["_entry_timestamp"]
        active = [
            position
            for position in active
            if position["exit_timestamp"] is None
            or position["exit_timestamp"] > entry_time
        ]
        gate = _portfolio_candidate_gate(active, candidate, config)
        public_candidate = {
            key: value
            for key, value in candidate.items()
            if not key.startswith("_")
        }
        if not gate["allowed"]:
            rejection_counts[gate["reason"]] += 1
            rejected.append(
                {
                    "symbol": candidate["symbol"],
                    "side": candidate["side"],
                    "entry_time": candidate["entry_time"],
                    "reason": gate["reason"],
                    "portfolio_state": gate["projected_state"],
                }
            )
            continue

        public_candidate["portfolio_state_at_entry"] = gate["projected_state"]
        accepted.append(public_candidate)
        active.append(
            {
                "symbol": candidate["symbol"],
                "side": candidate["side"],
                "cluster": candidate["cluster"],
                "notional": candidate["notional"],
                "exit_timestamp": candidate["_exit_timestamp"],
            }
        )

    accepted_by_exit = sorted(
        accepted,
        key=lambda trade: (
            _timestamp(trade.get("exit_time")),
            trade["symbol"],
            trade["side"],
        ),
    )
    capital = config.initial_capital
    equity_curve = [{"label": "INITIAL", "equity": round(capital, 2)}]
    for trade in accepted_by_exit:
        capital += float(trade.get("pnl") or 0)
        trade["portfolio_capital_after"] = round(capital, 2)
        equity_curve.append(
            {
                "label": trade.get("exit_time"),
                "equity": round(capital, 2),
            }
        )

    performance = calculate_performance(
        accepted_by_exit,
        initial_capital=config.initial_capital,
        final_capital=capital,
        equity_curve=equity_curve,
    )
    return {
        "engine_version": PORTFOLIO_REPLAY_VERSION,
        "model": "DETERMINISTIC_MULTI_SYMBOL_OVERLAP_AND_CLUSTER_GATE",
        "total_candidates": len(candidates),
        "total_trades": len(accepted_by_exit),
        "trades": accepted_by_exit,
        "rejected_candidates": rejected,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "equity_curve": equity_curve,
        "portfolio_policy": {
            **asdict(config),
            "cluster_source": (
                "EXPLICIT_SYMBOL_CLUSTER_MAP"
                if clusters
                else "SYMBOL_ISOLATED_NO_INFERRED_CORRELATION"
            ),
            "same_timestamp_priority": "CONFIDENCE_DESC_SYMBOL_ASC_SIDE_ASC",
            "exposure_denominator": "INITIAL_CAPITAL",
        },
        **performance,
    }


def _candidate_trades(symbol_results, clusters):
    candidates = []
    for raw_symbol, result in dict(symbol_results or {}).items():
        symbol = str(raw_symbol).upper()
        cluster = clusters.get(symbol, f"UNGROUPED::{symbol}")
        for raw_trade in list(dict(result or {}).get("trades") or []):
            trade = dict(raw_trade)
            sizing = dict(trade.get("sizing") or {})
            notional = float(sizing.get("notional") or 0)
            entry_timestamp = _timestamp(trade.get("entry_time"))
            exit_timestamp = _timestamp(trade.get("exit_time"))
            if notional <= 0 or entry_timestamp is None or exit_timestamp is None:
                continue
            candidates.append(
                {
                    **trade,
                    "symbol": symbol,
                    "cluster": cluster,
                    "notional": notional,
                    "_entry_timestamp": entry_timestamp,
                    "_exit_timestamp": exit_timestamp,
                }
            )
    return sorted(
        candidates,
        key=lambda trade: (
            trade["_entry_timestamp"],
            -float(trade.get("confidence") or 0),
            trade["symbol"],
            trade["side"],
        ),
    )


def _initial_active_positions(positions, clusters):
    active = []
    for raw_position in list(positions or []):
        position = dict(raw_position)
        symbol = str(position.get("symbol") or "").upper()
        side = str(position.get("side") or "").upper()
        notional = float(position.get("notional") or 0)
        if not symbol or side not in {"LONG", "SHORT"} or notional <= 0:
            raise ValueError("initial positions require symbol, LONG/SHORT side, and positive notional")
        active.append(
            {
                "symbol": symbol,
                "side": side,
                "cluster": str(
                    position.get("cluster")
                    or clusters.get(symbol)
                    or f"UNGROUPED::{symbol}"
                ),
                "notional": notional,
                "exit_timestamp": _timestamp(position.get("exit_time")),
            }
        )
    return active


def _portfolio_candidate_gate(active, candidate, config):
    projected = [*active, candidate]
    gross = sum(float(position["notional"]) for position in projected)
    cluster_gross = sum(
        float(position["notional"])
        for position in projected
        if position["cluster"] == candidate["cluster"]
    )
    state = {
        "open_positions": len(projected),
        "gross_exposure": round(gross, 4),
        "gross_exposure_percent": round(
            gross / config.initial_capital * 100,
            4,
        ),
        "candidate_cluster": candidate["cluster"],
        "cluster_exposure": round(cluster_gross, 4),
        "cluster_exposure_percent": round(
            cluster_gross / config.initial_capital * 100,
            4,
        ),
    }
    if len(projected) > config.max_open_positions:
        return {
            "allowed": False,
            "reason": "PORTFOLIO_MAX_OPEN_POSITIONS",
            "projected_state": state,
        }
    if state["gross_exposure_percent"] > config.max_gross_exposure_percent:
        return {
            "allowed": False,
            "reason": "PORTFOLIO_MAX_GROSS_EXPOSURE",
            "projected_state": state,
        }
    if state["cluster_exposure_percent"] > config.max_cluster_exposure_percent:
        return {
            "allowed": False,
            "reason": "PORTFOLIO_MAX_CLUSTER_EXPOSURE",
            "projected_state": state,
        }
    return {
        "allowed": True,
        "reason": None,
        "projected_state": state,
    }


def _timestamp(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    try:
        return normalize_timestamp_to_utc(value)
    except (AttributeError, TypeError, ValueError):
        return None
