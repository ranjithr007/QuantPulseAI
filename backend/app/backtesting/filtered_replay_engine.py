from collections import Counter
from dataclasses import asdict, dataclass
from types import SimpleNamespace

from app.backtesting.backtest_engine import _adverse_fill
from app.backtesting.backtest_engine import _bps_rate
from app.backtesting.backtest_engine import _exit_trigger
from app.backtesting.backtest_engine import _price
from app.backtesting.backtest_engine import _time_label
from app.backtesting.backtest_engine import _time_value
from app.backtesting.backtest_engine import chronological_candles
from app.backtesting.performance_engine import calculate_performance
from app.features.point_in_time_feature_service import build_feature_snapshot
from app.paper_trading.fill_model import build_fill_profile
from app.regimes.rules import detect_regime


ENGINE_VERSION = "filtered_replay_v1"
LONG_REGIMES = {
    "TRENDING_BULL",
    "HIGH_VOLATILITY_BREAKOUT",
    "LIQUIDITY_GRAB_BULLISH",
}
SHORT_REGIMES = {
    "TRENDING_BEAR",
    "HIGH_VOLATILITY_BREAKDOWN",
    "LIQUIDITY_GRAB_BEARISH",
}


@dataclass(frozen=True)
class FilteredReplayConfig:
    initial_capital: float = 10_000.0
    position_size_percent: float = 100.0
    min_confidence: float = 70.0
    stop_atr_multiple: float = 1.5
    target_atr_multiple: float = 3.5
    cooldown_candles: int = 3
    warmup_candles: int = 50
    fee_bps: float = 4.0
    slippage_bps: float = 2.0

    def __post_init__(self):
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be greater than zero")
        if not 0 < self.position_size_percent <= 100:
            raise ValueError("position_size_percent must be between 0 and 100")
        if not 0 <= self.min_confidence <= 100:
            raise ValueError("min_confidence must be between 0 and 100")
        if self.stop_atr_multiple <= 0 or self.target_atr_multiple <= 0:
            raise ValueError("ATR multiples must be greater than zero")
        if self.cooldown_candles < 0:
            raise ValueError("cooldown_candles cannot be negative")
        if self.warmup_candles < 50:
            raise ValueError("warmup_candles must be at least 50")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("fee_bps and slippage_bps cannot be negative")


def run_filtered_replay(
    candles,
    side,
    *,
    feature_resolver=None,
    initial_capital=10_000,
    position_size_percent=100,
    min_confidence=70,
    stop_atr_multiple=1.5,
    target_atr_multiple=3.5,
    cooldown_candles=3,
    warmup_candles=50,
    fee_bps=4,
    slippage_bps=2,
):
    requested_side = str(side or "").upper()
    if requested_side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")

    config = FilteredReplayConfig(
        initial_capital=float(initial_capital),
        position_size_percent=float(position_size_percent),
        min_confidence=float(min_confidence),
        stop_atr_multiple=float(stop_atr_multiple),
        target_atr_multiple=float(target_atr_multiple),
        cooldown_candles=int(cooldown_candles),
        warmup_candles=int(warmup_candles),
        fee_bps=float(fee_bps),
        slippage_bps=float(slippage_bps),
    )
    ordered = chronological_candles(candles)
    capital = config.initial_capital
    trades = []
    equity_curve = [{"label": _time_label(ordered[0]) if ordered else "START", "equity": round(capital, 2)}]
    decision_counts = Counter()
    rejection_counts = Counter()
    feature_source_counts = Counter()
    point_in_time_counts = Counter()
    decision_index = config.warmup_candles - 1
    cooldown_until = 0
    signal_armed = True
    exposed_candles = 0

    while decision_index < len(ordered) - 1 and capital > 0:
        decision = build_candle_decision(
            ordered[: decision_index + 1],
            requested_side,
            config.min_confidence,
            feature_resolver=feature_resolver,
        )
        decision_counts[decision["signal"]] += 1
        feature_source_counts[decision["feature_source"]] += 1
        point_in_time_counts.update(decision.get("point_in_time_flags") or {})

        if not decision["eligible"]:
            signal_armed = True
            rejection_counts.update(decision["blocked_reasons"])
            decision_index += 1
            continue

        if decision_index < cooldown_until:
            rejection_counts["COOLDOWN_ACTIVE"] += 1
            decision_index += 1
            continue

        if not signal_armed:
            rejection_counts["SIGNAL_NOT_REARMED"] += 1
            decision_index += 1
            continue

        entry_index = decision_index + 1
        entry_candle = ordered[entry_index]
        raw_entry = _price(entry_candle, "open_price", "close_price")
        if raw_entry is None:
            rejection_counts["MISSING_ENTRY_PRICE"] += 1
            decision_index += 1
            continue

        entry_fill = _adverse_fill(raw_entry, requested_side, config.slippage_bps, entering=True)
        atr = float(decision["features"]["atr"])
        stop_distance = atr * config.stop_atr_multiple
        target_distance = atr * config.target_atr_multiple
        if requested_side == "LONG":
            stop = entry_fill - stop_distance
            target = entry_fill + target_distance
        else:
            stop = entry_fill + stop_distance
            target = entry_fill - target_distance
        if min(stop, target) <= 0:
            rejection_counts["INVALID_ATR_LEVELS"] += 1
            decision_index += 1
            continue

        allocated_capital = capital * (config.position_size_percent / 100)
        quantity = allocated_capital / entry_fill
        exit_details = None
        for exit_index in range(entry_index, len(ordered)):
            candle = ordered[exit_index]
            trigger = _exit_trigger(candle, requested_side, stop, target)
            if trigger is not None:
                trigger_type, trigger_price = trigger
                exit_fill = _adverse_fill(
                    trigger_price,
                    requested_side,
                    config.slippage_bps,
                    entering=False,
                )
                exit_details = (exit_index, candle, trigger_type, trigger_price, exit_fill)
                break

        if exit_details is None:
            exit_index = len(ordered) - 1
            exit_candle = ordered[exit_index]
            raw_exit = _price(exit_candle, "close_price", "open_price")
            if raw_exit is None:
                break
            exit_details = (
                exit_index,
                exit_candle,
                "END_OF_DATA",
                raw_exit,
                _adverse_fill(raw_exit, requested_side, config.slippage_bps, entering=False),
            )

        exit_index, exit_candle, exit_reason, trigger_price, exit_fill = exit_details
        entry_fee = entry_fill * quantity * _bps_rate(config.fee_bps)
        exit_fee = exit_fill * quantity * _bps_rate(config.fee_bps)
        gross_pnl = (
            (exit_fill - entry_fill) * quantity
            if requested_side == "LONG"
            else (entry_fill - exit_fill) * quantity
        )
        fees = entry_fee + exit_fee
        net_pnl = gross_pnl - fees
        pnl_percent = (net_pnl / allocated_capital) * 100 if allocated_capital else 0
        capital += net_pnl
        exposed_candles += exit_index - entry_index + 1

        trades.append(
            {
                "side": requested_side,
                "decision_time": _time_value(ordered[decision_index]),
                "entry": round(entry_fill, 8),
                "entry_reference": round(raw_entry, 8),
                "entry_time": _time_value(entry_candle),
                "exit": round(exit_fill, 8),
                "exit_reference": round(trigger_price, 8),
                "exit_time": _time_value(exit_candle),
                "stop": round(stop, 8),
                "target": round(target, 8),
                "result": "WIN" if net_pnl > 0 else "LOSS" if net_pnl < 0 else "BREAKEVEN",
                "exit_reason": exit_reason,
                "gross_pnl": round(gross_pnl, 2),
                "fees": round(fees, 2),
                "pnl": round(net_pnl, 2),
                "pnl_percent": round(pnl_percent, 4),
                "capital_after": round(capital, 2),
                "duration_candles": exit_index - entry_index + 1,
                "regime": decision["regime"],
                "confidence": decision["confidence"],
                "feature_score": decision["features"]["final_score"],
                "atr": round(atr, 8),
                "feature_source": decision["feature_source"],
            }
        )
        equity_curve.append({"label": _time_label(exit_candle), "equity": round(capital, 2)})

        if exit_reason == "END_OF_DATA":
            break
        signal_armed = False
        cooldown_until = exit_index + config.cooldown_candles + 1
        decision_index = exit_index + 1

    performance = calculate_performance(
        trades,
        initial_capital=config.initial_capital,
        final_capital=capital,
        equity_curve=equity_curve,
    )
    candle_span = max(0, len(ordered) - 1)
    return {
        "engine_version": ENGINE_VERSION,
        "strategy": "CANDLE_RECONSTRUCTED_REGIME_FILTER_V1",
        "signal": requested_side,
        "candle_count": len(ordered),
        "total_trades": len(trades),
        "trades": trades,
        "equity_curve": equity_curve,
        "exposure_percent": round((exposed_candles / candle_span) * 100 if candle_span else 0, 2),
        "decision_summary": {
            "evaluated": sum(decision_counts.values()),
            "signals": dict(sorted(decision_counts.items())),
            "rejections": dict(sorted(rejection_counts.items())),
        },
        "historical_input_status": {
            "candles": "AVAILABLE",
            "features": "POINT_IN_TIME_SNAPSHOT_FIRST",
            "regime": "RECONSTRUCTED_FROM_CLOSED_CANDLES",
            "smc": "UNAVAILABLE_HISTORICALLY",
            "orderflow": "UNAVAILABLE_HISTORICALLY",
            "claim_scope": "CANDLE_FILTER_VALIDATION_NOT_FULL_AI_REPLAY",
        },
        "replay_provenance": {
            "feature_source_counts": dict(sorted(feature_source_counts.items())),
            "feature_source_preference": "POINT_IN_TIME_THEN_CANDLE_FALLBACK",
            "point_in_time_coverage": {
                "evaluated_decisions": sum(decision_counts.values()),
                "feature_snapshot_hits": point_in_time_counts.get("feature_snapshot_hit", 0),
                "feature_reconstructed_fallbacks": point_in_time_counts.get("feature_reconstructed_fallback", 0),
                "decision_snapshot_hits": point_in_time_counts.get("decision_snapshot_hit", 0),
                "thesis_snapshot_hits": point_in_time_counts.get("thesis_snapshot_hit", 0),
                "full_point_in_time_bundle_hits": point_in_time_counts.get("full_point_in_time_bundle_hit", 0),
                "feature_leakage_passes": point_in_time_counts.get("feature_leakage_pass", 0),
                "feature_leakage_partials": point_in_time_counts.get("feature_leakage_partial", 0),
                "feature_leakage_failures": point_in_time_counts.get("feature_leakage_fail", 0),
                "thesis_leakage_passes": point_in_time_counts.get("thesis_leakage_pass", 0),
                "thesis_leakage_partials": point_in_time_counts.get("thesis_leakage_partial", 0),
                "thesis_leakage_failures": point_in_time_counts.get("thesis_leakage_fail", 0),
            },
        },
        "execution_parity": _execution_parity_summary(trades, config),
        "eligibility_divergence": _eligibility_divergence_summary(rejection_counts),
        "assumptions": {
            **asdict(config),
            "entry_timing": "NEXT_CANDLE_OPEN",
            "intrabar_collision": "STOP_FIRST",
            "position_policy": "ONE_AT_A_TIME",
            "signal_reentry": "REQUIRES_GATE_RESET",
            "stop_model": "ATR_MULTIPLE",
            "target_model": "ATR_MULTIPLE",
            "reward_risk_ratio": round(config.target_atr_multiple / config.stop_atr_multiple, 4),
        },
        **performance,
    }


def build_candle_decision(candles, requested_side, min_confidence, *, feature_resolver=None):
    feature_contract = None
    feature_source = "CANDLE_RECONSTRUCTION"
    point_in_time_flags = {}
    if feature_resolver is not None and candles:
        feature_contract = feature_resolver(candles[-1].candle_time)
        if feature_contract is not None:
            metadata = feature_contract.get("_point_in_time") if isinstance(feature_contract, dict) else None
            point_in_time_flags = _point_in_time_flags(metadata)
            feature_source = (
                "POINT_IN_TIME_SNAPSHOT"
                if point_in_time_flags.get("feature_snapshot_hit")
                else "POINT_IN_TIME_FALLBACK"
            )

    if feature_contract is None:
        feature_contract = build_feature_snapshot("REPLAY", "REPLAY", candles)

    features = feature_contract["feature"] if "feature" in feature_contract else feature_contract
    trend_score = features["trend_score"]
    trend = features["trend"]
    momentum_score = features["momentum_score"]
    volatility_score = features["volatility_score"]
    liquidity_score = features["liquidity_score"]
    final_score = features["final_score"]
    atr = features["atr"]
    feature_snapshot = SimpleNamespace(
        TrendScore=trend_score,
        MomentumScore=momentum_score,
        VolatilityScore=volatility_score,
        LiquidityScore=liquidity_score,
        FinalScore=final_score,
    )
    regime = detect_regime(feature_snapshot)
    directional_strength = final_score if requested_side == "LONG" else 100 - final_score
    confidence = round((directional_strength + regime["confidence"]) / 2, 2)
    blocked = []

    if atr <= 0:
        blocked.append("ATR_UNAVAILABLE")
    if confidence < min_confidence:
        blocked.append("CONFIDENCE_BELOW_THRESHOLD")
    if requested_side == "LONG":
        if trend != "BULLISH" or trend_score < 65:
            blocked.append("TREND_NOT_BULLISH")
        if momentum_score < 60:
            blocked.append("MOMENTUM_NOT_BULLISH")
        if final_score <= 70:
            blocked.append("FEATURE_SIGNAL_NOT_LONG")
        if regime["regime"] not in LONG_REGIMES:
            blocked.append("REGIME_NOT_BULLISH")
    else:
        if trend != "BEARISH" or trend_score > 35:
            blocked.append("TREND_NOT_BEARISH")
        if momentum_score > 40:
            blocked.append("MOMENTUM_NOT_BEARISH")
        if final_score >= 40:
            blocked.append("FEATURE_SIGNAL_NOT_SHORT")
        if regime["regime"] not in SHORT_REGIMES:
            blocked.append("REGIME_NOT_BEARISH")

    return {
        "eligible": not blocked,
        "signal": requested_side if not blocked else "WAIT",
        "blocked_reasons": blocked,
        "confidence": confidence,
        "regime": regime["regime"],
        "feature_source": feature_source,
        "point_in_time_flags": point_in_time_flags,
        "features": {
            "trend": trend,
            "trend_score": trend_score,
            "momentum_score": momentum_score,
            "volatility_score": volatility_score,
            "liquidity_score": liquidity_score,
            "final_score": round(final_score, 2),
            "atr": atr,
        },
    }


def _point_in_time_flags(metadata):
    if not isinstance(metadata, dict):
        return {}

    feature_status = str(metadata.get("feature_leakage_status") or "").upper()
    thesis_status = str(metadata.get("thesis_leakage_status") or "").upper()
    feature_snapshot_found = bool(metadata.get("feature_snapshot_found"))
    decision_snapshot_found = bool(metadata.get("decision_snapshot_found"))
    thesis_snapshot_found = bool(metadata.get("thesis_snapshot_found"))

    flags = {
        "feature_snapshot_hit": 1 if feature_snapshot_found else 0,
        "feature_reconstructed_fallback": 0 if feature_snapshot_found else 1,
        "decision_snapshot_hit": 1 if decision_snapshot_found else 0,
        "thesis_snapshot_hit": 1 if thesis_snapshot_found else 0,
        "full_point_in_time_bundle_hit": 1 if feature_snapshot_found and decision_snapshot_found and thesis_snapshot_found else 0,
    }
    flags.update(_leakage_status_flags("feature_leakage", feature_status))
    flags.update(_leakage_status_flags("thesis_leakage", thesis_status))
    return flags


def _leakage_status_flags(prefix, status):
    return {
        f"{prefix}_pass": 1 if status == "PASS" else 0,
        f"{prefix}_partial": 1 if status == "PARTIAL" else 0,
        f"{prefix}_fail": 1 if status == "FAIL" else 0,
    }


def _execution_parity_summary(trades, config):
    replay_entry_slippage_pct = round(float(config.slippage_bps) / 100, 4)
    replay_exit_slippage_pct = round(float(config.slippage_bps) / 100, 4)

    if not trades:
        return {
            "source": "filtered_replay_execution_parity",
            "status": "NO_TRADES",
            "backtest_model": {
                "entry_slippage_pct": replay_entry_slippage_pct,
                "exit_slippage_pct": replay_exit_slippage_pct,
                "fee_bps": float(config.fee_bps),
                "round_trip_fee_percent": round(float(config.fee_bps) * 2 / 100, 4),
            },
            "paper_model": None,
            "summary": "No replay trades available for paper-vs-backtest fill comparison.",
        }

    paper_profiles = [
        build_fill_profile(
            side=trade.get("side"),
            planned_entry_price=trade.get("entry_reference") or trade.get("entry"),
            stop_loss=trade.get("stop"),
            target1=trade.get("target"),
            confidence=trade.get("confidence"),
            risk_reward=_trade_risk_reward(trade),
            fee_bps=config.fee_bps,
        )
        for trade in trades
    ]

    avg_paper_entry_slippage_pct = round(_average(profile.get("entry_slippage_pct") for profile in paper_profiles), 4)
    avg_paper_exit_slippage_pct = round(_average(profile.get("exit_slippage_pct") for profile in paper_profiles), 4)
    avg_paper_effective_rr = round(_average(profile.get("effective_risk_reward") for profile in paper_profiles), 4)
    avg_replay_rr = round(_average(_trade_risk_reward(trade) for trade in trades), 4)
    slippage_gap_pct = round(avg_paper_entry_slippage_pct - replay_entry_slippage_pct, 4)

    if avg_paper_entry_slippage_pct <= replay_entry_slippage_pct * 0.9:
        parity_label = "PAPER_TIGHTER_THAN_REPLAY"
    elif avg_paper_entry_slippage_pct >= replay_entry_slippage_pct * 1.1:
        parity_label = "PAPER_WIDER_THAN_REPLAY"
    else:
        parity_label = "PAPER_SIMILAR_TO_REPLAY"

    return {
        "source": "filtered_replay_execution_parity",
        "status": "OK",
        "backtest_model": {
            "entry_slippage_pct": replay_entry_slippage_pct,
            "exit_slippage_pct": replay_exit_slippage_pct,
            "fee_bps": float(config.fee_bps),
            "round_trip_fee_percent": round(float(config.fee_bps) * 2 / 100, 4),
            "reward_risk_ratio": round(float(config.target_atr_multiple) / float(config.stop_atr_multiple), 4),
        },
        "paper_model": {
            "fill_model": "paper_trade_fill_model_v1",
            "avg_entry_slippage_pct": avg_paper_entry_slippage_pct,
            "avg_exit_slippage_pct": avg_paper_exit_slippage_pct,
            "avg_effective_risk_reward": avg_paper_effective_rr,
            "round_trip_fee_percent": round(float(config.fee_bps) * 2 / 100, 4),
        },
        "comparison": {
            "trade_count_compared": len(paper_profiles),
            "entry_slippage_gap_pct": slippage_gap_pct,
            "risk_reward_gap": round(avg_paper_effective_rr - avg_replay_rr, 4),
            "parity_label": parity_label,
        },
        "summary": _execution_parity_summary_text(parity_label, slippage_gap_pct),
    }


def _execution_parity_summary_text(parity_label, slippage_gap_pct):
    if parity_label == "PAPER_WIDER_THAN_REPLAY":
        return f"Paper fill assumptions are wider than replay by about {abs(slippage_gap_pct):.4f}% on entry."
    if parity_label == "PAPER_TIGHTER_THAN_REPLAY":
        return f"Paper fill assumptions are tighter than replay by about {abs(slippage_gap_pct):.4f}% on entry."
    return "Paper fill assumptions are close to replay slippage for this run."


def _eligibility_divergence_summary(rejection_counts):
    total_rejections = sum(rejection_counts.values())
    if total_rejections == 0:
        return {
            "source": "filtered_replay_eligibility_divergence",
            "status": "NO_REJECTIONS",
            "summary": "No replay rejections were recorded, so there is no eligibility divergence to compare.",
        }

    comparable_counts = Counter()
    replay_only_counts = Counter()
    unknown_counts = Counter()

    for reason, count in rejection_counts.items():
        family, label = _replay_rejection_family(reason)
        if family == "COMPARABLE_TO_PAPER_GATE":
            comparable_counts[label] += count
        elif family == "REPLAY_ONLY_GATE":
            replay_only_counts[label] += count
        else:
            unknown_counts[reason] += count

    comparable_total = sum(comparable_counts.values())
    replay_only_total = sum(replay_only_counts.values())
    unknown_total = sum(unknown_counts.values())
    coverage_percent = round((comparable_total / total_rejections) * 100, 2) if total_rejections else 0.0

    top_replay_blockers = [
        {"reason": reason, "count": count}
        for reason, count in rejection_counts.most_common(5)
    ]

    return {
        "source": "filtered_replay_eligibility_divergence",
        "status": "OK",
        "replay_rejections": {
            "total": total_rejections,
            "top_blockers": top_replay_blockers,
        },
        "comparable_to_paper_gate": {
            "count": comparable_total,
            "coverage_percent": coverage_percent,
            "families": dict(sorted(comparable_counts.items())),
        },
        "replay_only_gate": {
            "count": replay_only_total,
            "families": dict(sorted(replay_only_counts.items())),
        },
        "paper_only_gate": {
            "count": 4,
            "families": {
                "DERIVATIVES_DATA_REQUIRED": [
                    "Futures funding rate unavailable",
                    "Futures open interest unavailable",
                ],
                "RISK_DECISION_REQUIRED": [
                    "No risk decision found for trade plan",
                    "Risk decision is not APPROVE",
                ],
                "RISK_FRESHNESS_REQUIRED": [
                    "Risk decision is stale",
                ],
                "RISK_PLAN_ALIGNMENT_REQUIRED": [
                    "Risk signal does not match trade side",
                    "Risk entry does not match trade entry",
                    "Risk stop_loss does not match trade stop_loss",
                    "Risk target1 does not match trade target1",
                    "Risk decision is older than trade plan",
                ],
            },
        },
        "unknown_replay_gate": {
            "count": unknown_total,
            "families": dict(sorted(unknown_counts.items())),
        },
        "summary": _eligibility_divergence_summary_text(
            comparable_counts,
            replay_only_counts,
            coverage_percent,
        ),
    }


def _replay_rejection_family(reason):
    comparable_map = {
        "CONFIDENCE_BELOW_THRESHOLD": "CONFIDENCE_GATE",
        "TREND_NOT_BULLISH": "TREND_ALIGNMENT_GATE",
        "TREND_NOT_BEARISH": "TREND_ALIGNMENT_GATE",
        "MOMENTUM_NOT_BULLISH": "MOMENTUM_ALIGNMENT_GATE",
        "MOMENTUM_NOT_BEARISH": "MOMENTUM_ALIGNMENT_GATE",
        "FEATURE_SIGNAL_NOT_LONG": "FEATURE_SIGNAL_GATE",
        "FEATURE_SIGNAL_NOT_SHORT": "FEATURE_SIGNAL_GATE",
        "REGIME_NOT_BULLISH": "REGIME_GATE",
        "REGIME_NOT_BEARISH": "REGIME_GATE",
    }
    replay_only_map = {
        "ATR_UNAVAILABLE": "REPLAY_MARKET_DATA_GATE",
        "MISSING_ENTRY_PRICE": "REPLAY_ENTRY_PRICING_GATE",
        "INVALID_ATR_LEVELS": "REPLAY_RISK_LEVEL_GATE",
        "COOLDOWN_ACTIVE": "REPLAY_COOLDOWN_GATE",
        "SIGNAL_NOT_REARMED": "REPLAY_SIGNAL_REARM_GATE",
    }

    if reason in comparable_map:
        return "COMPARABLE_TO_PAPER_GATE", comparable_map[reason]
    if reason in replay_only_map:
        return "REPLAY_ONLY_GATE", replay_only_map[reason]
    return "UNKNOWN", reason


def _eligibility_divergence_summary_text(comparable_counts, replay_only_counts, coverage_percent):
    comparable_label = next(iter(comparable_counts), None)
    replay_only_label = next(iter(replay_only_counts), None)

    if comparable_label and replay_only_label:
        return (
            f"About {coverage_percent:.2f}% of replay rejections map cleanly to live paper gates, "
            f"led by {comparable_label}; replay-only friction is led by {replay_only_label}."
        )
    if comparable_label:
        return (
            f"About {coverage_percent:.2f}% of replay rejections map cleanly to live paper gates, "
            f"led by {comparable_label}."
        )
    if replay_only_label:
        return (
            f"Replay rejections are dominated by execution-only rules such as {replay_only_label}; "
            "live paper gating differences still need separate risk/derivatives checks."
        )
    return "Replay rejection coverage could not be mapped cleanly to live paper gating families."


def _trade_risk_reward(trade):
    side = str(trade.get("side") or "").upper()
    entry = _safe_float(trade.get("entry_reference") or trade.get("entry"))
    stop = _safe_float(trade.get("stop"))
    target = _safe_float(trade.get("target"))

    if None in {entry, stop, target}:
        return None

    if side == "LONG":
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target

    if risk <= 0 or reward <= 0:
        return None

    return reward / risk


def _average(values):
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
