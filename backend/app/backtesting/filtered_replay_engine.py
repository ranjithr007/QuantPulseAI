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
from app.features.liquidity_features import calculate_liquidity
from app.features.momentum_features import calculate_momentum
from app.features.trend_features import calculate_trend
from app.features.volatility_features import calculate_volatility
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
    decision_index = config.warmup_candles - 1
    cooldown_until = 0
    signal_armed = True
    exposed_candles = 0

    while decision_index < len(ordered) - 1 and capital > 0:
        decision = build_candle_decision(
            ordered[: decision_index + 1],
            requested_side,
            config.min_confidence,
        )
        decision_counts[decision["signal"]] += 1

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
            "features": "RECONSTRUCTED_FROM_CLOSED_CANDLES",
            "regime": "RECONSTRUCTED_FROM_CLOSED_CANDLES",
            "smc": "UNAVAILABLE_HISTORICALLY",
            "orderflow": "UNAVAILABLE_HISTORICALLY",
            "claim_scope": "CANDLE_FILTER_VALIDATION_NOT_FULL_AI_REPLAY",
        },
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


def build_candle_decision(candles, requested_side, min_confidence):
    trend_score, trend = calculate_trend(candles)
    momentum_score = calculate_momentum(candles)
    volatility_score, atr = calculate_volatility(candles)
    liquidity_score = calculate_liquidity(candles)
    final_score = (
        trend_score * 0.35
        + momentum_score * 0.35
        + volatility_score * 0.15
        + liquidity_score * 0.15
    )
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
