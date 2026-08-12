from collections import Counter
from collections.abc import Sequence
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
from app.regimes.rules import detect_regime, regime_direction
from app.intelligence.multi_timeframe_engine import BEARISH_BIASES
from app.intelligence.multi_timeframe_engine import BULLISH_BIASES
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.utils.freshness import normalize_timestamp_to_utc


ENGINE_VERSION = "filtered_replay_v1"


class _CandlePrefixView(Sequence):
    """O(1) read-only view over candles closed through one decision index."""

    def __init__(self, candles, end):
        self._candles = candles
        self._end = end

    def __len__(self):
        return self._end

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(self._end)
            return self._candles[start:stop:step]
        normalized = index + self._end if index < 0 else index
        if normalized < 0 or normalized >= self._end:
            raise IndexError(index)
        return self._candles[normalized]

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
DIRECTIONAL_LONG_ENTRY_RESEARCH_REGIMES = {
    "BULL_PULLBACK",
    "RANGE_ACCUMULATION",
}
DIRECTIONAL_SHORT_ENTRY_RESEARCH_REGIMES = {
    "BEAR_RALLY",
    "RANGE_DISTRIBUTION",
}
DIRECTIONAL_LONG_RESEARCH_REGIMES = (
    LONG_REGIMES | DIRECTIONAL_LONG_ENTRY_RESEARCH_REGIMES
)
DIRECTIONAL_SHORT_RESEARCH_REGIMES = (
    SHORT_REGIMES | DIRECTIONAL_SHORT_ENTRY_RESEARCH_REGIMES
)
GATE_PROFILES = {
    "STRICT": {
        "long_trend_score": 65,
        "long_momentum_score": 60,
        "long_final_score": 70,
        "long_regime_required": True,
        "short_trend_score": 35,
        "short_momentum_score": 40,
        "short_final_score": 40,
        "short_regime_required": True,
        "enforce_decision_chain": True,
    },
    # Research-only profile. It measures signal coverage under a directional
    # filter without changing the production STRICT gate.
    "RESEARCH_RELAXED": {
        "long_trend_score": 55,
        "long_momentum_score": 50,
        "long_final_score": 60,
        "long_regime_required": False,
        "short_trend_score": 45,
        "short_momentum_score": 50,
        "short_final_score": 45,
        "short_regime_required": False,
        "enforce_decision_chain": False,
    },
    # Research-only SHORT profile derived from failure-pattern diagnostics.
    # It avoids late/exhausted shorts and countertrend bear rallies while
    # allowing neutral/range regimes that do not strongly conflict.
    "SHORT_EDGE_RESEARCH": {
        "long_trend_score": 65,
        "long_momentum_score": 60,
        "long_final_score": 70,
        "long_regime_required": True,
        "short_trend_score": 45,
        "short_trend_score_min": 25,
        "short_momentum_score": 45,
        "short_final_score": 45,
        "short_final_score_min": 35,
        "short_regime_required": False,
        "short_blocked_regimes": {
            *LONG_REGIMES,
            "BEAR_RALLY",
            "HIGH_VOLATILITY_BREAKDOWN",
        },
        "confidence_max": 65,
        "enforce_decision_chain": False,
    },
    # Research-only profile that isolates one hypothesis from the R5
    # untouched-symbol diagnostic: BEAR_RALLY shorts require point-in-time
    # evidence that the counter-trend rally has exhausted.
    "BEAR_RALLY_EXHAUSTION_RESEARCH": {
        "long_trend_score": 55,
        "long_momentum_score": 50,
        "long_final_score": 60,
        "long_regime_required": False,
        "short_trend_score": 45,
        "short_momentum_score": 50,
        "short_final_score": 45,
        "short_regime_required": False,
        "short_bear_rally_requires_exhaustion": True,
        "enforce_decision_chain": False,
    },
    # Attribution cell A: expand only directional regime membership while all
    # production feature and decision-chain requirements remain enforced.
    "DIRECTIONAL_REGIME_EXPANSION_RESEARCH": {
        "long_trend_score": 65,
        "long_momentum_score": 60,
        "long_final_score": 70,
        "long_regime_required": True,
        "long_allowed_regimes": DIRECTIONAL_LONG_RESEARCH_REGIMES,
        "short_trend_score": 35,
        "short_momentum_score": 40,
        "short_final_score": 40,
        "short_regime_required": True,
        "short_allowed_regimes": DIRECTIONAL_SHORT_RESEARCH_REGIMES,
        "enforce_decision_chain": True,
    },
    # Attribution cell B: in the four added pullback/range regimes only, a
    # fully actionable decision chain plus local order-flow/SMC confirmation
    # substitutes for structurally incompatible feature-entry thresholds.
    "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH": {
        "long_trend_score": 65,
        "long_momentum_score": 60,
        "long_final_score": 70,
        "long_regime_required": True,
        "long_allowed_regimes": DIRECTIONAL_LONG_RESEARCH_REGIMES,
        "short_trend_score": 35,
        "short_momentum_score": 40,
        "short_final_score": 40,
        "short_regime_required": True,
        "short_allowed_regimes": DIRECTIONAL_SHORT_RESEARCH_REGIMES,
        "directional_entry_confirmation": True,
        "enforce_decision_chain": True,
    },
}


@dataclass(frozen=True)
class FilteredReplayConfig:
    initial_capital: float = 10_000.0
    position_size_percent: float = 100.0
    min_confidence: float = MIN_ENTRY_CONFIDENCE
    stop_atr_multiple: float = 1.5
    target_atr_multiple: float = 3.5
    cooldown_candles: int = 3
    warmup_candles: int = 50
    fee_bps: float = 4.0
    slippage_bps: float = 2.0
    risk_percent_per_trade: float | None = None
    target_trade_volatility_percent: float | None = None
    max_leverage: float = 1.0
    max_open_positions: int = 20
    max_gross_exposure_percent: float = 500.0
    initial_portfolio_positions: tuple = ()
    collision_policy: str = "STOP_FIRST"
    profit_protection_mode: str = "NONE"
    profit_protection_activation_r: float = 1.0
    timeframe_minutes: int = 60
    funding_interval_hours: float = 8.0
    maintenance_margin_rate: float = 0.005
    maintenance_margin_brackets: tuple = ()

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
        if self.risk_percent_per_trade is not None and not 0 < self.risk_percent_per_trade <= 100:
            raise ValueError("risk_percent_per_trade must be greater than 0 and at most 100")
        if (
            self.target_trade_volatility_percent is not None
            and not 0 < self.target_trade_volatility_percent <= 100
        ):
            raise ValueError(
                "target_trade_volatility_percent must be greater than 0 and at most 100"
            )
        if (
            self.risk_percent_per_trade is not None
            and self.target_trade_volatility_percent is not None
        ):
            raise ValueError("fixed-risk and volatility-targeted sizing are mutually exclusive")
        if self.max_leverage < 1:
            raise ValueError("max_leverage must be at least 1")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be at least 1")
        if self.max_gross_exposure_percent <= 0:
            raise ValueError("max_gross_exposure_percent must be greater than zero")
        collision_policy = str(self.collision_policy or "").upper()
        if collision_policy not in {"STOP_FIRST", "TARGET_FIRST", "LOWER_TIMEFRAME_REQUIRED"}:
            raise ValueError(
                "collision_policy must be STOP_FIRST, TARGET_FIRST, or LOWER_TIMEFRAME_REQUIRED"
            )
        object.__setattr__(self, "collision_policy", collision_policy)
        protection_mode = str(self.profit_protection_mode or "").upper()
        if protection_mode not in {"NONE", "BREAKEVEN_AFTER_R"}:
            raise ValueError(
                "profit_protection_mode must be NONE or BREAKEVEN_AFTER_R"
            )
        if self.profit_protection_activation_r <= 0:
            raise ValueError("profit_protection_activation_r must be positive")
        object.__setattr__(self, "profit_protection_mode", protection_mode)
        if self.timeframe_minutes <= 0 or self.funding_interval_hours <= 0:
            raise ValueError("timeframe and funding intervals must be positive")
        if not 0 <= self.maintenance_margin_rate < 1:
            raise ValueError("maintenance_margin_rate must be between 0 and 1")
        object.__setattr__(
            self,
            "maintenance_margin_brackets",
            _normalize_margin_brackets(self.maintenance_margin_brackets),
        )


def run_filtered_replay(
    candles,
    side,
    *,
    feature_resolver=None,
    stack_resolver=None,
    initial_capital=10_000,
    position_size_percent=100,
    min_confidence=MIN_ENTRY_CONFIDENCE,
    stop_atr_multiple=1.5,
    target_atr_multiple=3.5,
    cooldown_candles=3,
    warmup_candles=50,
    fee_bps=4,
    slippage_bps=2,
    gate_profile="STRICT",
    regime_detector=None,
    risk_percent_per_trade=None,
    target_trade_volatility_percent=None,
    max_leverage=1,
    max_open_positions=20,
    max_gross_exposure_percent=500,
    initial_portfolio_positions=None,
    collision_policy="STOP_FIRST",
    profit_protection_mode="NONE",
    profit_protection_activation_r=1.0,
    timeframe_minutes=60,
    funding_interval_hours=8,
    maintenance_margin_rate=0.005,
    maintenance_margin_brackets=None,
    mark_price_records=None,
    decision_cache=None,
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
        risk_percent_per_trade=(
            None
            if risk_percent_per_trade is None
            else float(risk_percent_per_trade)
        ),
        target_trade_volatility_percent=(
            None
            if target_trade_volatility_percent is None
            else float(target_trade_volatility_percent)
        ),
        max_leverage=float(max_leverage),
        max_open_positions=int(max_open_positions),
        max_gross_exposure_percent=float(max_gross_exposure_percent),
        initial_portfolio_positions=tuple(initial_portfolio_positions or ()),
        collision_policy=collision_policy,
        profit_protection_mode=profit_protection_mode,
        profit_protection_activation_r=float(profit_protection_activation_r),
        timeframe_minutes=int(timeframe_minutes),
        funding_interval_hours=float(funding_interval_hours),
        maintenance_margin_rate=float(maintenance_margin_rate),
        maintenance_margin_brackets=tuple(maintenance_margin_brackets or ()),
    )
    gate_profile_key = str(gate_profile or "STRICT").upper()
    if gate_profile_key not in GATE_PROFILES:
        raise ValueError(f"gate_profile must be one of {sorted(GATE_PROFILES)}")
    regime_detector = regime_detector or detect_regime
    regime_detector_key = getattr(regime_detector, "__name__", str(regime_detector))
    ordered = chronological_candles(candles)
    capital = config.initial_capital
    trades = []
    equity_curve = [{"label": _time_label(ordered[0]) if ordered else "START", "equity": round(capital, 2)}]
    decision_counts = Counter()
    rejection_counts = Counter()
    regime_counts = Counter()
    regime_direction_counts = Counter()
    regime_source_counts = Counter()
    rejection_combination_counts = Counter()
    gate_pass_counts = Counter()
    score_distributions = {
        name: _new_score_distribution()
        for name in (
            "confidence",
            "regime_confidence",
            "trend_score",
            "momentum_score",
            "volatility_score",
            "liquidity_score",
            "final_score",
        )
    }
    master_signal_diagnostics = {
        "all_decisions": _new_master_signal_diagnostics(),
        "regime_gate_pass_decisions": _new_master_signal_diagnostics(),
    }
    directional_entry_funnel = _new_directional_entry_funnel()
    feature_source_counts = Counter()
    point_in_time_counts = Counter()
    stack_state_counts = Counter()
    decision_index = config.warmup_candles - 1
    cooldown_until = 0
    signal_armed = True
    exposed_candles = 0
    initial_portfolio = _portfolio_state(
        config.initial_portfolio_positions,
        capital,
    )

    while decision_index < len(ordered) - 1 and capital > 0:
        decision_timestamp = _decision_timestamp(ordered[decision_index])
        decision_key = (
            decision_timestamp,
            requested_side,
            config.min_confidence,
            gate_profile_key,
            regime_detector_key,
        )
        decision = (
            decision_cache.get(decision_key)
            if decision_cache is not None
            else None
        )
        if decision is None:
            decision = build_candle_decision(
                _CandlePrefixView(ordered, decision_index + 1),
                requested_side,
                config.min_confidence,
                feature_resolver=feature_resolver,
                stack_context=(
                    stack_resolver(decision_timestamp)
                    if stack_resolver is not None
                    else None
                ),
                gate_profile=gate_profile_key,
                regime_detector=regime_detector,
            )
            if decision_cache is not None:
                decision_cache[decision_key] = decision
        decision_counts[decision["signal"]] += 1
        decision_regime = decision.get("regime") or "UNKNOWN"
        regime_counts[decision_regime] += 1
        regime_direction_counts[regime_direction(decision_regime)] += 1
        regime_source_counts[decision.get("regime_source") or "UNKNOWN"] += 1
        blocked_reasons = tuple(sorted(set(decision.get("blocked_reasons") or ())))
        rejection_combination_counts[
            " | ".join(blocked_reasons) if blocked_reasons else "PASS"
        ] += 1
        gate_pass_counts.update(_independent_gate_passes(blocked_reasons))
        _update_master_signal_diagnostics(
            master_signal_diagnostics["all_decisions"],
            decision,
        )
        _update_directional_entry_funnel(
            directional_entry_funnel,
            decision,
            requested_side,
            config.min_confidence,
        )
        if not any(
            reason.startswith("REGIME_") or reason.startswith("BEAR_RALLY_")
            for reason in blocked_reasons
        ):
            _update_master_signal_diagnostics(
                master_signal_diagnostics["regime_gate_pass_decisions"],
                decision,
            )
        _update_score_distribution(score_distributions["confidence"], decision.get("confidence"))
        _update_score_distribution(
            score_distributions["regime_confidence"],
            decision.get("regime_confidence"),
        )
        for score_name in (
            "trend_score",
            "momentum_score",
            "volatility_score",
            "liquidity_score",
            "final_score",
        ):
            _update_score_distribution(
                score_distributions[score_name],
                (decision.get("features") or {}).get(score_name),
            )
        feature_source_counts[decision["feature_source"]] += 1
        point_in_time_counts.update(decision.get("point_in_time_flags") or {})
        stack_state_counts[decision.get("timeframe_stack_state") or "NOT_SUPPLIED"] += 1

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

        capital_before = capital
        sizing = _position_sizing(
            capital=capital,
            entry=entry_fill,
            stop_distance=stop_distance,
            position_size_percent=config.position_size_percent,
            max_leverage=config.max_leverage,
            risk_percent_per_trade=config.risk_percent_per_trade,
            target_trade_volatility_percent=config.target_trade_volatility_percent,
            atr=atr,
        )
        quantity = sizing["quantity"]
        planned_risk_amount = sizing["planned_risk_amount"]
        sizing_mode = sizing["mode"]
        allocated_capital = sizing["allocated_capital"]
        portfolio_gate = _portfolio_gate(
            initial_portfolio,
            side=requested_side,
            candidate_notional=sizing["notional"],
            capital=capital,
            max_open_positions=config.max_open_positions,
            max_gross_exposure_percent=config.max_gross_exposure_percent,
        )
        if not portfolio_gate["allowed"]:
            rejection_counts[portfolio_gate["reason"]] += 1
            decision_index += 1
            continue
        exit_details = None
        active_stop = stop
        protection_activated = False
        protection_activation_time = None
        for exit_index in range(entry_index, len(ordered)):
            candle = ordered[exit_index]
            trigger = _exit_trigger_with_policy(
                candle,
                requested_side,
                active_stop,
                target,
                config.collision_policy,
            )
            if trigger is not None:
                trigger_type, trigger_price = trigger
                if trigger_type == "STOP" and protection_activated:
                    trigger_type = "PROTECTED_STOP"
                exit_fill = _adverse_fill(
                    trigger_price,
                    requested_side,
                    config.slippage_bps,
                    entering=False,
                )
                exit_details = (
                    exit_index,
                    candle,
                    trigger_type,
                    trigger_price,
                    exit_fill,
                    active_stop,
                )
                break
            if not protection_activated:
                protected_stop, activated = _profit_protection_stop(
                    candle,
                    requested_side,
                    entry_fill,
                    stop_distance,
                    active_stop,
                    mode=config.profit_protection_mode,
                    activation_r=config.profit_protection_activation_r,
                )
                if activated:
                    active_stop = protected_stop
                    protection_activated = True
                    protection_activation_time = _time_value(candle)

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
                active_stop,
            )

        (
            exit_index,
            exit_candle,
            exit_reason,
            trigger_price,
            exit_fill,
            exit_stop,
        ) = exit_details
        entry_fee = entry_fill * quantity * _bps_rate(config.fee_bps)
        exit_fee = exit_fill * quantity * _bps_rate(config.fee_bps)
        gross_pnl = (
            (exit_fill - entry_fill) * quantity
            if requested_side == "LONG"
            else (entry_fill - exit_fill) * quantity
        )
        fees = entry_fee + exit_fee
        entry_slippage_cost = abs(entry_fill - raw_entry) * quantity
        exit_slippage_cost = abs(exit_fill - trigger_price) * quantity
        duration_candles = exit_index - entry_index + 1
        funding_rate = _replay_funding_rate(decision.get("timeframe_stack"))
        funding_events = int(
            (duration_candles * config.timeframe_minutes)
            // (config.funding_interval_hours * 60)
        )
        funding_payment = (
            entry_fill
            * quantity
            * funding_rate
            * funding_events
            * (1 if requested_side == "LONG" else -1)
        )
        net_pnl = gross_pnl - fees - funding_payment
        pnl_denominator = (
            capital_before
            if (
                config.risk_percent_per_trade is not None
                or config.target_trade_volatility_percent is not None
            )
            else allocated_capital
        )
        pnl_percent = (net_pnl / pnl_denominator) * 100 if pnl_denominator else 0
        capital += net_pnl
        exposed_candles += duration_candles
        excursions = _excursion_metrics(
            ordered,
            entry_index,
            exit_index,
            requested_side,
            entry_fill,
            stop,
            target,
        )
        collision = _intrabar_collision(
            exit_candle,
            requested_side,
            exit_stop,
            target,
        )
        result_label = (
            "WIN" if net_pnl > 0 else "LOSS" if net_pnl < 0 else "BREAKEVEN"
        )
        loss_class = _loss_classification(
            result_label,
            exit_reason,
            excursions,
        )
        mark_price_path = _mark_price_path(
            mark_price_records,
            entry_candle,
            exit_candle,
        )
        liquidation = _liquidation_diagnostics(
            mark_price_path or ordered[entry_index : exit_index + 1],
            requested_side,
            entry_fill,
            quantity,
            capital_before,
            config.maintenance_margin_rate,
            maintenance_margin_brackets=(
                config.maintenance_margin_brackets
                or _replay_margin_brackets(decision.get("timeframe_stack"))
            ),
            price_source=(
                "HISTORICAL_MARK_PRICE_KLINES"
                if mark_price_path
                else "CANDLE_HIGH_LOW_PROXY"
            ),
        )

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
                "effective_stop_at_exit": round(exit_stop, 8),
                "target": round(target, 8),
                "result": result_label,
                "exit_reason": exit_reason,
                "loss_class": loss_class,
                "intrabar_collision": collision,
                "gross_pnl": round(gross_pnl, 2),
                "fees": round(fees, 2),
                "execution_costs": {
                    "entry_slippage": round(entry_slippage_cost, 4),
                    "exit_slippage": round(exit_slippage_cost, 4),
                    "fees": round(fees, 4),
                    "funding_payment": round(funding_payment, 4),
                    "funding_rate": funding_rate,
                    "funding_events": funding_events,
                    "total": round(
                        entry_slippage_cost
                        + exit_slippage_cost
                        + fees
                        + funding_payment,
                        4,
                    ),
                },
                "pnl": round(net_pnl, 2),
                "pnl_percent": round(pnl_percent, 4),
                "capital_after": round(capital, 2),
                "duration_candles": duration_candles,
                "sizing": {
                    "mode": sizing_mode,
                    "quantity": round(quantity, 8),
                    "notional": round(quantity * entry_fill, 4),
                    "planned_risk_amount": (
                        round(planned_risk_amount, 4)
                        if planned_risk_amount is not None
                        else None
                    ),
                    "effective_leverage": round(
                        (quantity * entry_fill) / capital_before,
                        4,
                    ),
                },
                "portfolio_state_at_entry": portfolio_gate["projected_state"],
                "liquidation": liquidation,
                "regime": decision["regime"],
                "confidence": decision["confidence"],
                "trend_score": decision["features"]["trend_score"],
                "momentum_score": decision["features"]["momentum_score"],
                "feature_score": decision["features"]["final_score"],
                "atr": round(atr, 8),
                "feature_source": decision["feature_source"],
                "timeframe_stack": decision.get("timeframe_stack"),
                "profit_protection": {
                    "mode": config.profit_protection_mode,
                    "activation_r": config.profit_protection_activation_r,
                    "activated": protection_activated,
                    "activation_time": protection_activation_time,
                    "protected_stop": (
                        round(active_stop, 8) if protection_activated else None
                    ),
                    "activation_applies_from_next_candle": True,
                },
                "excursions": excursions,
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
    evaluated_decisions = sum(decision_counts.values())
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
            "evaluated": evaluated_decisions,
            "signals": dict(sorted(decision_counts.items())),
            "rejections": dict(sorted(rejection_counts.items())),
            "regimes": dict(sorted(regime_counts.items())),
            "regime_percentages": _percentage_distribution(
                regime_counts,
                evaluated_decisions,
            ),
            "regime_directions": dict(sorted(regime_direction_counts.items())),
            "regime_sources": dict(sorted(regime_source_counts.items())),
            "regime_direction_percentages": _percentage_distribution(
                regime_direction_counts,
                evaluated_decisions,
            ),
            "independent_gate_pass_counts": dict(sorted(gate_pass_counts.items())),
            "independent_gate_pass_percentages": _percentage_distribution(
                gate_pass_counts,
                evaluated_decisions,
            ),
            "rejection_combinations": dict(
                rejection_combination_counts.most_common()
            ),
            "feature_score_distributions": {
                name: _serialize_score_distribution(distribution)
                for name, distribution in sorted(score_distributions.items())
            },
            "master_signal_diagnostics": {
                scope: _serialize_master_signal_diagnostics(diagnostics)
                for scope, diagnostics in sorted(master_signal_diagnostics.items())
            },
            "directional_entry_funnel": _serialize_directional_entry_funnel(
                directional_entry_funnel
            ),
        },
        "historical_input_status": {
            "candles": "AVAILABLE",
            "features": "POINT_IN_TIME_SNAPSHOT_FIRST",
            "regime": "RECONSTRUCTED_FROM_CLOSED_CANDLES",
            "timeframe_stack": (
                "POINT_IN_TIME_1H_4H_1D"
                if stack_resolver is not None
                else "NOT_SUPPLIED"
            ),
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
            "timeframe_stack_states": dict(sorted(stack_state_counts.items())),
        },
        "execution_parity": _execution_parity_summary(trades, config),
        "eligibility_divergence": _eligibility_divergence_summary(rejection_counts),
        "loss_attribution": _loss_attribution_summary(trades),
        "portfolio_state": {
            "initial": initial_portfolio,
            "policy": {
                "max_open_positions": config.max_open_positions,
                "max_gross_exposure_percent": config.max_gross_exposure_percent,
            },
            "model": "PRE_DECISION_STATE_PLUS_SEQUENTIAL_REPLAY_POSITION",
        },
        "assumptions": {
            **asdict(config),
            "gate_profile": gate_profile_key,
            "regime_detector": regime_detector_key,
            "entry_timing": "NEXT_CANDLE_OPEN",
            "intrabar_collision": config.collision_policy,
            "collision_policy": config.collision_policy,
            "sizing_mode": (
                "FIXED_RISK_CAPPED"
                if config.risk_percent_per_trade is not None
                else "VOLATILITY_TARGETED_CAPPED"
                if config.target_trade_volatility_percent is not None
                else "CAPITAL_PERCENT"
            ),
            "funding_model": "ENTRY_RATE_APPLIED_PER_8H_EVENT",
            "mark_price_model": (
                "HISTORICAL_MARK_PRICE_KLINES"
                if mark_price_records
                else "CANDLE_HIGH_LOW_PROXY"
            ),
            "margin_bracket_model": (
                "POINT_IN_TIME_VERSIONED_SNAPSHOT_WITH_CONFIG_FALLBACK"
            ),
            "position_policy": "ONE_AT_A_TIME",
            "signal_reentry": "REQUIRES_GATE_RESET",
            "stop_model": "ATR_MULTIPLE",
            "target_model": "ATR_MULTIPLE",
            "timeframe_stack_policy": (
                "CONFLICTS_BLOCK_WITHOUT_CONFIDENCE_PENALTY"
                if stack_resolver is not None
                else "NOT_APPLIED"
            ),
            "reward_risk_ratio": round(config.target_atr_multiple / config.stop_atr_multiple, 4),
        },
        **performance,
    }


def _excursion_metrics(
    candles,
    entry_index,
    exit_index,
    side,
    entry,
    stop,
    target,
    *,
    post_exit_lookahead=10,
):
    risk_distance = abs(float(entry) - float(stop))
    target_distance = abs(float(target) - float(entry))
    path = list(candles[entry_index : exit_index + 1])
    favorable = []
    adverse = []
    for offset, candle in enumerate(path):
        high = _price(candle, "high_price", "close_price")
        low = _price(candle, "low_price", "close_price")
        if high is None or low is None:
            continue
        if side == "LONG":
            favorable.append((max(0.0, high - entry), offset))
            adverse.append((max(0.0, entry - low), offset))
        else:
            favorable.append((max(0.0, entry - low), offset))
            adverse.append((max(0.0, high - entry), offset))

    max_favorable, time_to_mfe = max(favorable, default=(0.0, None))
    max_adverse, time_to_mae = max(adverse, default=(0.0, None))
    lookahead_end = min(len(candles), exit_index + 1 + int(post_exit_lookahead))
    post_exit = list(candles[exit_index + 1 : lookahead_end])
    post_stop_favorable = 0.0
    for candle in post_exit:
        high = _price(candle, "high_price", "close_price")
        low = _price(candle, "low_price", "close_price")
        if high is None or low is None:
            continue
        move = (
            max(0.0, high - entry)
            if side == "LONG"
            else max(0.0, entry - low)
        )
        post_stop_favorable = max(post_stop_favorable, move)

    return {
        "mfe_price": round(max_favorable, 8),
        "mae_price": round(max_adverse, 8),
        "mfe_r": round(max_favorable / risk_distance, 4) if risk_distance else None,
        "mae_r": round(max_adverse / risk_distance, 4) if risk_distance else None,
        "time_to_mfe_candles": time_to_mfe,
        "time_to_mae_candles": time_to_mae,
        "post_exit_lookahead_candles": int(post_exit_lookahead),
        "post_stop_max_favorable_r": (
            round(post_stop_favorable / risk_distance, 4)
            if risk_distance
            else None
        ),
        "post_stop_target_recovered": post_stop_favorable >= target_distance,
    }


def _intrabar_collision(candle, side, stop, target):
    high = _price(candle, "high_price", "close_price")
    low = _price(candle, "low_price", "close_price")
    if high is None or low is None:
        return False
    if side == "LONG":
        return low <= stop and high >= target
    return high >= stop and low <= target


def _exit_trigger_with_policy(candle, side, stop, target, collision_policy):
    if not _intrabar_collision(candle, side, stop, target):
        return _exit_trigger(candle, side, stop, target)

    open_price = _price(candle, "open_price", "close_price")
    if side == "LONG":
        if open_price is not None and open_price <= stop:
            return "STOP", open_price
        if open_price is not None and open_price >= target:
            return "TARGET", open_price
    else:
        if open_price is not None and open_price >= stop:
            return "STOP", open_price
        if open_price is not None and open_price <= target:
            return "TARGET", open_price

    policy = str(collision_policy or "STOP_FIRST").upper()
    if policy == "TARGET_FIRST":
        return "TARGET", target
    if policy == "LOWER_TIMEFRAME_REQUIRED":
        return "AMBIGUOUS_COLLISION", stop
    return "STOP", stop


def _replay_funding_rate(stack_context):
    try:
        return float(
            stack_context["derivatives"]["funding"].get("rate") or 0.0
        )
    except (KeyError, TypeError, ValueError):
        return 0.0


def _replay_margin_brackets(stack_context):
    try:
        brackets = stack_context["derivatives"]["margin_brackets"]["brackets"]
        return tuple(brackets or ())
    except (KeyError, TypeError):
        return ()


def _position_sizing(
    *,
    capital,
    entry,
    stop_distance,
    position_size_percent,
    max_leverage,
    risk_percent_per_trade,
    target_trade_volatility_percent=None,
    atr=None,
):
    capital = float(capital)
    entry = float(entry)
    stop_distance = float(stop_distance)
    max_leverage = float(max_leverage)
    notional_cap = capital * max_leverage * (float(position_size_percent) / 100)
    if target_trade_volatility_percent is not None:
        atr = float(atr)
        if atr <= 0:
            raise ValueError("atr must be greater than zero for volatility sizing")
        target_move_amount = capital * (
            float(target_trade_volatility_percent) / 100
        )
        quantity = min(target_move_amount / atr, notional_cap / entry)
        planned_risk_amount = None
        mode = "VOLATILITY_TARGETED_CAPPED"
    elif risk_percent_per_trade is None:
        planned_risk_amount = None
        quantity = notional_cap / entry
        mode = "CAPITAL_PERCENT"
    else:
        planned_risk_amount = capital * (float(risk_percent_per_trade) / 100)
        quantity = min(
            planned_risk_amount / stop_distance,
            notional_cap / entry,
        )
        mode = "FIXED_RISK_CAPPED"

    notional = quantity * entry
    return {
        "mode": mode,
        "quantity": quantity,
        "notional": notional,
        "notional_cap": notional_cap,
        "planned_risk_amount": planned_risk_amount,
        "allocated_capital": notional / max_leverage,
        "effective_leverage": notional / capital if capital else 0.0,
    }


def _portfolio_state(positions, capital):
    normalized = []
    for item in positions or ():
        if not isinstance(item, dict):
            raise ValueError("initial portfolio positions must be mappings")
        side = str(item.get("side") or "").upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError("portfolio position side must be LONG or SHORT")
        notional = float(item.get("notional") or 0)
        if notional <= 0:
            raise ValueError("portfolio position notional must be greater than zero")
        normalized.append(
            {
                "symbol": str(item.get("symbol") or "UNKNOWN").upper(),
                "side": side,
                "notional": notional,
            }
        )
    gross = sum(item["notional"] for item in normalized)
    net = sum(
        item["notional"] * (1 if item["side"] == "LONG" else -1)
        for item in normalized
    )
    denominator = float(capital)
    return {
        "open_positions": len(normalized),
        "gross_exposure": round(gross, 4),
        "net_exposure": round(net, 4),
        "gross_exposure_percent": round(
            (gross / denominator) * 100 if denominator else 0,
            4,
        ),
        "net_exposure_percent": round(
            (net / denominator) * 100 if denominator else 0,
            4,
        ),
        "positions": normalized,
    }


def _portfolio_gate(
    state,
    *,
    side,
    candidate_notional,
    capital,
    max_open_positions,
    max_gross_exposure_percent,
):
    projected_open = int(state["open_positions"]) + 1
    projected_gross = float(state["gross_exposure"]) + float(candidate_notional)
    projected_net = float(state["net_exposure"]) + float(candidate_notional) * (
        1 if side == "LONG" else -1
    )
    gross_percent = (projected_gross / float(capital)) * 100 if capital else 0
    projected = {
        "open_positions": projected_open,
        "gross_exposure": round(projected_gross, 4),
        "net_exposure": round(projected_net, 4),
        "gross_exposure_percent": round(gross_percent, 4),
        "net_exposure_percent": round(
            (projected_net / float(capital)) * 100 if capital else 0,
            4,
        ),
    }
    if projected_open > int(max_open_positions):
        return {
            "allowed": False,
            "reason": "PORTFOLIO_MAX_OPEN_POSITIONS",
            "projected_state": projected,
        }
    if gross_percent > float(max_gross_exposure_percent):
        return {
            "allowed": False,
            "reason": "PORTFOLIO_MAX_GROSS_EXPOSURE",
            "projected_state": projected,
        }
    return {
        "allowed": True,
        "reason": None,
        "projected_state": projected,
    }


def _liquidation_diagnostics(
    candles,
    side,
    entry,
    quantity,
    capital,
    maintenance_margin_rate,
    *,
    maintenance_margin_brackets=(),
    price_source="CANDLE_HIGH_LOW_PROXY",
):
    notional = float(entry) * float(quantity)
    effective_leverage = notional / float(capital) if capital else 0.0
    bracket = _select_margin_bracket(
        notional,
        maintenance_margin_brackets,
        maintenance_margin_rate,
    )
    maintenance_margin_rate = bracket["maintenance_margin_rate"]
    maintenance_amount = bracket["maintenance_amount"]
    tier_max_leverage = bracket.get("max_leverage")
    leverage_within_tier = (
        True
        if tier_max_leverage in (None, 0)
        else effective_leverage <= float(tier_max_leverage)
    )
    if effective_leverage <= 1:
        return {
            "checked": True,
            "price": None,
            "touched": False,
            "effective_leverage": round(effective_leverage, 4),
            "leverage_within_tier": leverage_within_tier,
            "margin_bracket": bracket,
            "price_source": price_source,
        }

    initial_margin = notional / effective_leverage
    if side == "LONG":
        liquidation_price = (
            (notional - initial_margin - maintenance_amount)
            / (float(quantity) * (1 - maintenance_margin_rate))
        )
        touched = any(
            (_price(candle, "low_price", "close_price") or float("inf"))
            <= liquidation_price
            for candle in candles
        )
    else:
        liquidation_price = (
            (notional + initial_margin + maintenance_amount)
            / (float(quantity) * (1 + maintenance_margin_rate))
        )
        touched = any(
            (_price(candle, "high_price", "close_price") or 0)
            >= liquidation_price
            for candle in candles
        )
    return {
        "checked": True,
        "price": round(max(0.0, liquidation_price), 8),
        "touched": touched,
        "effective_leverage": round(effective_leverage, 4),
        "leverage_within_tier": leverage_within_tier,
        "maintenance_margin_rate": float(maintenance_margin_rate),
        "maintenance_amount": float(maintenance_amount),
        "margin_bracket": bracket,
        "price_source": price_source,
    }


def _normalize_margin_brackets(brackets):
    normalized = []
    for index, bracket in enumerate(brackets or ()):
        if not isinstance(bracket, dict):
            raise ValueError("maintenance margin brackets must be mappings")
        floor = float(bracket.get("notional_floor", bracket.get("notionalFloor", 0)))
        cap_value = bracket.get("notional_cap", bracket.get("notionalCap"))
        cap = float(cap_value) if cap_value is not None else float("inf")
        rate = float(
            bracket.get(
                "maintenance_margin_rate",
                bracket.get("maintMarginRatio"),
            )
        )
        amount = float(
            bracket.get(
                "maintenance_amount",
                bracket.get("cum", 0),
            )
        )
        if floor < 0 or cap <= floor or not 0 <= rate < 1 or amount < 0:
            raise ValueError("invalid maintenance margin bracket")
        normalized.append(
            {
                "bracket": int(bracket.get("bracket", index + 1)),
                "notional_floor": floor,
                "notional_cap": cap,
                "maintenance_margin_rate": rate,
                "maintenance_amount": amount,
                "max_leverage": (
                    float(bracket["initialLeverage"])
                    if bracket.get("initialLeverage") is not None
                    else bracket.get("max_leverage")
                ),
                "source": bracket.get("source", "EXCHANGE_BRACKET_SNAPSHOT"),
            }
        )
    return tuple(sorted(normalized, key=lambda item: item["notional_floor"]))


def _select_margin_bracket(notional, brackets, fallback_rate):
    for bracket in brackets or ():
        if bracket["notional_floor"] <= notional < bracket["notional_cap"]:
            return dict(bracket)
    return {
        "bracket": None,
        "notional_floor": 0.0,
        "notional_cap": None,
        "maintenance_margin_rate": float(fallback_rate),
        "maintenance_amount": 0.0,
        "max_leverage": None,
        "source": "CONFIG_FALLBACK",
    }


def _mark_price_path(records, entry_candle, exit_candle):
    start = normalize_timestamp_to_utc(_decision_timestamp(entry_candle))
    end = normalize_timestamp_to_utc(_decision_timestamp(exit_candle))
    if start is None or end is None:
        return []
    selected = []
    for record in records or ():
        timestamp = normalize_timestamp_to_utc(
            (
                record.get("close_time")
                if isinstance(record, dict)
                else getattr(record, "close_time", None)
            )
        )
        if timestamp is not None and start <= timestamp <= end:
            selected.append(record)
    return selected


def _loss_classification(result, exit_reason, excursions):
    if result == "WIN":
        return "WIN"
    if result == "BREAKEVEN":
        return "BREAKEVEN"
    if exit_reason == "PROTECTED_STOP":
        return "PROFIT_PROTECTION_EXIT"
    if excursions.get("post_stop_target_recovered"):
        return "STOP_TOO_TIGHT_OR_ENTRY_EARLY"
    if (excursions.get("mfe_r") or 0) >= 1:
        return "PROFIT_GIVEBACK"
    if (excursions.get("mfe_r") or 0) < 0.25 and (excursions.get("mae_r") or 0) >= 1:
        return "IMMEDIATE_WRONG_DIRECTION"
    if exit_reason == "END_OF_DATA":
        return "NO_PROGRESS_END_OF_WINDOW"
    return "ORDINARY_STOP_LOSS"


def _profit_protection_stop(
    candle,
    side,
    entry,
    risk_distance,
    current_stop,
    *,
    mode,
    activation_r,
):
    if str(mode or "NONE").upper() != "BREAKEVEN_AFTER_R":
        return current_stop, False
    activation_distance = float(risk_distance) * float(activation_r)
    if str(side).upper() == "LONG":
        favorable_price = _price(candle, "high_price", "close_price")
        activated = (
            favorable_price is not None
            and favorable_price >= float(entry) + activation_distance
        )
    else:
        favorable_price = _price(candle, "low_price", "close_price")
        activated = (
            favorable_price is not None
            and favorable_price <= float(entry) - activation_distance
        )
    return (float(entry), True) if activated else (current_stop, False)


def _loss_attribution_summary(trades):
    loss_classes = Counter(
        trade.get("loss_class") or "UNCLASSIFIED"
        for trade in trades
        if trade.get("result") == "LOSS"
    )
    mfe_values = [
        trade["excursions"]["mfe_r"]
        for trade in trades
        if (trade.get("excursions") or {}).get("mfe_r") is not None
    ]
    mae_values = [
        trade["excursions"]["mae_r"]
        for trade in trades
        if (trade.get("excursions") or {}).get("mae_r") is not None
    ]
    return {
        "source": "filtered_replay_loss_attribution",
        "loss_classes": dict(sorted(loss_classes.items())),
        "average_mfe_r": round(_average(mfe_values), 4) if mfe_values else None,
        "average_mae_r": round(_average(mae_values), 4) if mae_values else None,
        "same_candle_collisions": sum(
            1 for trade in trades if trade.get("intrabar_collision")
        ),
        "classification_policy": "DIAGNOSTIC_ONLY_NOT_A_STRATEGY_GATE",
    }


def build_candle_decision(
    candles,
    requested_side,
    min_confidence,
    *,
    feature_resolver=None,
    stack_context=None,
    gate_profile="STRICT",
    regime_detector=None,
):
    regime_detector = regime_detector or detect_regime
    feature_contract = None
    feature_source = "CANDLE_RECONSTRUCTION"
    point_in_time_flags = {}
    if feature_resolver is not None and candles:
        feature_contract = feature_resolver(_decision_timestamp(candles[-1]))
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
    regime = _stateful_regime_from_stack(stack_context)
    regime_source = "POINT_IN_TIME_STATEFUL_STACK"
    if regime is None:
        regime = regime_detector(feature_snapshot)
        regime_source = "STATELESS_FEATURE_FALLBACK"
    directional_strength = final_score if requested_side == "LONG" else 100 - final_score
    confidence = round((directional_strength + regime["confidence"]) / 2, 2)
    blocked = []
    research_gate_evidence = {}
    profile = GATE_PROFILES.get(str(gate_profile or "STRICT").upper())
    if profile is None:
        raise ValueError(f"gate_profile must be one of {sorted(GATE_PROFILES)}")

    _, stack_blocks = _timeframe_stack_gate(
        stack_context,
        requested_side,
        enforce_decision_chain=profile.get("enforce_decision_chain", True),
    )
    blocked.extend(stack_blocks)

    if atr <= 0:
        blocked.append("ATR_UNAVAILABLE")
    if confidence < min_confidence:
        blocked.append("CONFIDENCE_BELOW_THRESHOLD")
    if confidence > profile.get("confidence_max", 100):
        blocked.append("CONFIDENCE_ABOVE_PROFILE_WINDOW")
    if requested_side == "LONG":
        if trend_score < profile["long_trend_score"]:
            blocked.append("TREND_NOT_BULLISH")
        if momentum_score < profile["long_momentum_score"]:
            blocked.append("MOMENTUM_NOT_BULLISH")
        if final_score <= profile["long_final_score"]:
            blocked.append("FEATURE_SIGNAL_NOT_LONG")
        long_allowed_regimes = profile.get("long_allowed_regimes", LONG_REGIMES)
        if profile["long_regime_required"] and regime["regime"] not in long_allowed_regimes:
            blocked.append("REGIME_NOT_BULLISH")
    else:
        if trend_score < profile.get("short_trend_score_min", 0):
            blocked.append("TREND_TOO_EXTENDED_BEARISH")
        if trend_score > profile["short_trend_score"]:
            blocked.append("TREND_NOT_BEARISH")
        if momentum_score > profile["short_momentum_score"]:
            blocked.append("MOMENTUM_NOT_BEARISH")
        if final_score < profile.get("short_final_score_min", 0):
            blocked.append("FEATURE_SIGNAL_TOO_EXTENDED_SHORT")
        if final_score >= profile["short_final_score"]:
            blocked.append("FEATURE_SIGNAL_NOT_SHORT")
        short_allowed_regimes = profile.get("short_allowed_regimes", SHORT_REGIMES)
        if profile["short_regime_required"] and regime["regime"] not in short_allowed_regimes:
            blocked.append("REGIME_NOT_BEARISH")
        if regime["regime"] in profile.get("short_blocked_regimes", set()):
            blocked.append("REGIME_CONFLICT_OR_REVERSAL")
        if (
            regime["regime"] == "BEAR_RALLY"
            and profile.get("short_bear_rally_requires_exhaustion")
        ):
            exhaustion = _bear_rally_exhaustion_evidence(stack_context)
            research_gate_evidence["bear_rally_exhaustion"] = exhaustion
            if not exhaustion["confirmed"]:
                blocked.append("BEAR_RALLY_EXHAUSTION_NOT_CONFIRMED")

    if (
        profile.get("directional_entry_confirmation")
        and (
            requested_side == "LONG"
            and regime["regime"] in DIRECTIONAL_LONG_ENTRY_RESEARCH_REGIMES
            or requested_side == "SHORT"
            and regime["regime"] in DIRECTIONAL_SHORT_ENTRY_RESEARCH_REGIMES
        )
    ):
        confirmation = _directional_entry_confirmation_evidence(
            stack_context,
            requested_side,
        )
        research_gate_evidence["directional_entry_confirmation"] = confirmation
        if confirmation["confirmed"]:
            replaceable = (
                {
                    "TREND_NOT_BULLISH",
                    "MOMENTUM_NOT_BULLISH",
                    "FEATURE_SIGNAL_NOT_LONG",
                }
                if requested_side == "LONG"
                else {
                    "TREND_TOO_EXTENDED_BEARISH",
                    "TREND_NOT_BEARISH",
                    "MOMENTUM_NOT_BEARISH",
                    "FEATURE_SIGNAL_TOO_EXTENDED_SHORT",
                    "FEATURE_SIGNAL_NOT_SHORT",
                }
            )
            replaced = sorted(set(blocked) & replaceable)
            blocked = [reason for reason in blocked if reason not in replaceable]
            confirmation["replaced_gate_rejections"] = replaced
        else:
            blocked.append("DIRECTIONAL_ENTRY_CONFIRMATION_NOT_CONFIRMED")

    return {
        "eligible": not blocked,
        "signal": requested_side if not blocked else "WAIT",
        "blocked_reasons": blocked,
        "confidence": confidence,
        "regime": regime["regime"],
        "regime_confidence": regime["confidence"],
        "regime_source": regime_source,
        "regime_detector": getattr(regime_detector, "__name__", str(regime_detector)),
        "feature_source": feature_source,
        "point_in_time_flags": point_in_time_flags,
        "timeframe_stack_state": (
            (stack_context.get("confirmation") or {}).get("stack_state")
            if isinstance(stack_context, dict)
            else None
        ),
        "timeframe_stack": stack_context,
        "research_gate_evidence": research_gate_evidence,
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


def _bear_rally_exhaustion_evidence(stack_context):
    evidence = {
        "confirmed": False,
        "seller_control": False,
        "buyer_exhaustion": False,
        "bearish_structure": False,
        "source": "POINT_IN_TIME_1H_ORDERFLOW_AND_SMC",
    }
    if not isinstance(stack_context, dict) or stack_context.get("status") != "READY":
        evidence["reason"] = "TIMEFRAME_STACK_UNAVAILABLE"
        return evidence
    timeframes = list(stack_context.get("timeframes") or [])
    if not timeframes:
        evidence["reason"] = "ENTRY_TIMEFRAME_UNAVAILABLE"
        return evidence

    intelligence = dict(timeframes[0].get("intelligence") or {})
    orderflow = dict(intelligence.get("orderflow") or {})
    smc = dict(intelligence.get("smc") or {})
    delta = _optional_float(orderflow.get("delta"))
    buyer_strength = _optional_float(orderflow.get("buyer_strength"))
    seller_strength = _optional_float(orderflow.get("seller_strength"))
    buy_volume = _optional_float(orderflow.get("buy_volume"))
    sell_volume = _optional_float(orderflow.get("sell_volume"))
    orderflow_signal = str(orderflow.get("signal") or "").upper()

    strength_confirms = (
        buyer_strength is not None
        and seller_strength is not None
        and seller_strength > buyer_strength
    )
    volume_confirms = (
        buy_volume is not None
        and sell_volume is not None
        and sell_volume > buy_volume
    )
    seller_control = (
        orderflow_signal in {"SELL", "STRONG_SELL", "SELLERS"}
        or (delta is not None and delta < 0 and (strength_confirms or volume_confirms))
    )
    exhaustion = str(
        orderflow.get("exhaustion")
        or orderflow.get("exhaustion_type")
        or ""
    ).upper()
    buyer_exhaustion = exhaustion == "BUYER_EXHAUSTION"
    bos = dict(smc.get("bos") or {})
    bearish_structure = (
        bool(bos.get("detected"))
        and str(bos.get("direction") or "").upper() == "BEARISH"
    ) or str(smc.get("bias") or "").upper() in {"SHORT", "BEARISH"}

    evidence.update(
        {
            "confirmed": bool(
                seller_control and (buyer_exhaustion or bearish_structure)
            ),
            "seller_control": bool(seller_control),
            "buyer_exhaustion": bool(buyer_exhaustion),
            "bearish_structure": bool(bearish_structure),
            "orderflow_signal": orderflow_signal or None,
            "delta": delta,
            "reason": (
                "SELLER_CONTROL_WITH_RALLY_EXHAUSTION"
                if seller_control and (buyer_exhaustion or bearish_structure)
                else "EXHAUSTION_EVIDENCE_INCOMPLETE"
            ),
        }
    )
    return evidence


def _directional_entry_confirmation_evidence(stack_context, requested_side):
    side = str(requested_side or "").upper()
    evidence = {
        "confirmed": False,
        "side": side,
        "orderflow_aligned": False,
        "structure_aligned": False,
        "source": "POINT_IN_TIME_DECISION_TIMEFRAME_ORDERFLOW_OR_SMC",
    }
    if side not in {"LONG", "SHORT"}:
        evidence["reason"] = "INVALID_SIDE"
        return evidence
    if not isinstance(stack_context, dict) or stack_context.get("status") != "READY":
        evidence["reason"] = "TIMEFRAME_STACK_UNAVAILABLE"
        return evidence

    decision_timeframe = str(stack_context.get("decision_chain_timeframe") or "")
    record = next(
        (
            item
            for item in (stack_context.get("timeframes") or ())
            if str(item.get("timeframe") or "") == decision_timeframe
        ),
        None,
    )
    intelligence = record.get("intelligence") if isinstance(record, dict) else None
    if not isinstance(intelligence, dict):
        evidence["reason"] = "DECISION_TIMEFRAME_INTELLIGENCE_UNAVAILABLE"
        evidence["decision_timeframe"] = decision_timeframe or None
        return evidence

    orderflow = dict(intelligence.get("orderflow") or {})
    smc = dict(intelligence.get("smc") or {})
    delta = _optional_float(orderflow.get("delta"))
    buyer_strength = _optional_float(orderflow.get("buyer_strength"))
    seller_strength = _optional_float(orderflow.get("seller_strength"))
    buy_volume = _optional_float(orderflow.get("buy_volume"))
    sell_volume = _optional_float(orderflow.get("sell_volume"))
    orderflow_signal = str(orderflow.get("signal") or "").upper()

    if side == "LONG":
        strength_aligned = (
            buyer_strength is not None
            and seller_strength is not None
            and buyer_strength > seller_strength
        )
        volume_aligned = (
            buy_volume is not None
            and sell_volume is not None
            and buy_volume > sell_volume
        )
        orderflow_aligned = (
            orderflow_signal in {"BUY", "STRONG_BUY", "BUYERS"}
            or (delta is not None and delta > 0 and (strength_aligned or volume_aligned))
        )
        structure_direction = "BULLISH"
        structure_biases = {"LONG", "BULLISH"}
    else:
        strength_aligned = (
            buyer_strength is not None
            and seller_strength is not None
            and seller_strength > buyer_strength
        )
        volume_aligned = (
            buy_volume is not None
            and sell_volume is not None
            and sell_volume > buy_volume
        )
        orderflow_aligned = (
            orderflow_signal in {"SELL", "STRONG_SELL", "SELLERS"}
            or (delta is not None and delta < 0 and (strength_aligned or volume_aligned))
        )
        structure_direction = "BEARISH"
        structure_biases = {"SHORT", "BEARISH"}

    bos = dict(smc.get("bos") or {})
    structure_aligned = (
        bool(bos.get("detected"))
        and str(bos.get("direction") or "").upper() == structure_direction
    ) or str(smc.get("bias") or "").upper() in structure_biases
    confirmed = bool(orderflow_aligned or structure_aligned)
    evidence.update(
        {
            "confirmed": confirmed,
            "decision_timeframe": decision_timeframe,
            "orderflow_aligned": bool(orderflow_aligned),
            "structure_aligned": bool(structure_aligned),
            "orderflow_signal": orderflow_signal or None,
            "delta": delta,
            "reason": (
                "LOCAL_DIRECTIONAL_CONFIRMATION_PRESENT"
                if confirmed
                else "LOCAL_DIRECTIONAL_CONFIRMATION_ABSENT"
            ),
        }
    )
    return evidence


def _optional_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


_DIRECTIONAL_FUNNEL_STAGES = (
    "SAME_SIDE_CANDIDATE_REGIME",
    "LOCAL_CONFIRMATION",
    "CONFIDENCE_AT_OR_ABOVE_THRESHOLD",
    "ATR_AVAILABLE",
    "TIMEFRAME_COMPATIBLE",
    "MASTER_SIGNAL_SAME_SIDE",
    "CONTRADICTION_ALLOWED",
    "RISK_APPROVED",
    "EXECUTOR_READY",
    "FINAL_ELIGIBLE",
)


def _new_directional_entry_funnel():
    return {
        "evaluated": 0,
        "stage_counts": Counter(),
        "condition_pass_counts": Counter(),
        "first_failure_counts": Counter(),
        "candidate_regimes": Counter(),
        "confirmed_candidate_score_distributions": {
            name: _new_score_distribution()
            for name in (
                "composite_confidence",
                "directional_strength",
                "regime_confidence",
            )
        },
        "master_candidate_chain_audit": {
            "evaluated": 0,
            "contradiction_statuses": Counter(),
            "contradiction_trade_allowed": Counter(),
            "conflict_scores": _new_score_distribution(),
            "master_signal_scores": _new_score_distribution(),
            "master_signal_confidences": _new_score_distribution(),
            "risk_confidences": _new_score_distribution(),
            "conflict_names": Counter(),
            "conflict_severities": Counter(),
            "bias_maps": {},
            "risk_decisions": Counter(),
            "risk_reasons": Counter(),
            "executor_verdicts": Counter(),
            "current_price_availability": Counter(),
        },
    }


def _update_directional_entry_funnel(
    diagnostics,
    decision,
    requested_side,
    min_confidence,
):
    observation = _directional_entry_funnel_observation(
        decision,
        requested_side,
        min_confidence,
    )
    diagnostics["evaluated"] += 1
    candidate_regime = observation["candidate_regime"]
    if candidate_regime:
        diagnostics["candidate_regimes"][candidate_regime] += 1
        if observation["conditions"]["LOCAL_CONFIRMATION"]:
            for name, value in observation["confidence_inputs"].items():
                _update_score_distribution(
                    diagnostics["confirmed_candidate_score_distributions"][name],
                    value,
                )

    cumulative = True
    first_failure = None
    for stage in _DIRECTIONAL_FUNNEL_STAGES:
        passed = bool(observation["conditions"][stage])
        if candidate_regime and passed:
            diagnostics["condition_pass_counts"][stage] += 1
        cumulative = cumulative and passed
        if cumulative:
            diagnostics["stage_counts"][stage] += 1
        elif first_failure is None:
            first_failure = stage
    if candidate_regime and first_failure is not None:
        diagnostics["first_failure_counts"][first_failure] += 1
    master_index = _DIRECTIONAL_FUNNEL_STAGES.index("MASTER_SIGNAL_SAME_SIDE")
    if candidate_regime and all(
        observation["conditions"][stage]
        for stage in _DIRECTIONAL_FUNNEL_STAGES[: master_index + 1]
    ):
        _update_master_candidate_chain_audit(
            diagnostics["master_candidate_chain_audit"],
            observation["chain_audit"],
        )


def _directional_entry_funnel_observation(decision, requested_side, min_confidence):
    side = str(requested_side or "").upper()
    regime = str(decision.get("regime") or "")
    candidate_regimes = (
        DIRECTIONAL_LONG_ENTRY_RESEARCH_REGIMES
        if side == "LONG"
        else DIRECTIONAL_SHORT_ENTRY_RESEARCH_REGIMES
    )
    candidate_regime = regime if regime in candidate_regimes else None
    evidence = (
        (decision.get("research_gate_evidence") or {}).get(
            "directional_entry_confirmation"
        )
        or {}
    )
    stack = decision.get("timeframe_stack") or {}
    chain = stack.get("decision_chain") if isinstance(stack, dict) else None
    chain = chain if isinstance(chain, dict) else {}
    chain_signal = str((chain.get("signal") or {}).get("signal") or "").upper()
    contradiction = dict(chain.get("contradiction") or {})
    risk = dict(chain.get("risk") or {})
    executor = dict(chain.get("executor") or {})
    decision_timeframe = str(stack.get("decision_chain_timeframe") or "")
    decision_record = next(
        (
            item
            for item in (stack.get("timeframes") or ())
            if str(item.get("timeframe") or "") == decision_timeframe
        ),
        None,
    )
    decision_intelligence = (
        decision_record.get("intelligence")
        if isinstance(decision_record, dict)
        else None
    )
    blocked = set(decision.get("blocked_reasons") or ())
    timeframe_blocks = {
        "TIMEFRAME_STACK_UNAVAILABLE",
        "HIGHER_TIMEFRAME_CONFLICT",
        "TIMEFRAME_PERMISSION_CONFLICT",
        "TIMEFRAME_STACK_STRONG_CONFLICT",
    }
    confidence = _optional_float(decision.get("confidence"))
    final_score = _optional_float((decision.get("features") or {}).get("final_score"))
    regime_confidence = _optional_float(decision.get("regime_confidence"))
    atr = _optional_float((decision.get("features") or {}).get("atr"))
    return {
        "candidate_regime": candidate_regime,
        "chain_audit": {
            "master_signal": dict(chain.get("signal") or {}),
            "contradiction": contradiction,
            "risk": risk,
            "executor": executor,
            "current_price_available": bool(
                isinstance(decision_intelligence, dict)
                and decision_intelligence.get("current_price") is not None
            ),
        },
        "confidence_inputs": {
            "composite_confidence": confidence,
            "directional_strength": (
                final_score
                if side == "LONG" or final_score is None
                else 100 - final_score
            ),
            "regime_confidence": regime_confidence,
        },
        "conditions": {
            "SAME_SIDE_CANDIDATE_REGIME": candidate_regime is not None,
            "LOCAL_CONFIRMATION": bool(evidence.get("confirmed")),
            "CONFIDENCE_AT_OR_ABOVE_THRESHOLD": (
                confidence is not None and confidence >= float(min_confidence)
            ),
            "ATR_AVAILABLE": atr is not None and atr > 0,
            "TIMEFRAME_COMPATIBLE": not bool(blocked & timeframe_blocks),
            "MASTER_SIGNAL_SAME_SIDE": chain_signal == side,
            "CONTRADICTION_ALLOWED": bool(contradiction.get("trade_allowed")),
            "RISK_APPROVED": str(risk.get("decision") or "").upper() == "APPROVE",
            "EXECUTOR_READY": (
                str(executor.get("verdict") or "").upper() == "WOULD_QUEUE"
            ),
            "FINAL_ELIGIBLE": bool(decision.get("eligible")),
        },
    }


def _serialize_directional_entry_funnel(diagnostics):
    evaluated = int(diagnostics.get("evaluated") or 0)
    candidates = int(
        (diagnostics.get("stage_counts") or {}).get(
            "SAME_SIDE_CANDIDATE_REGIME",
            0,
        )
    )
    return {
        "evaluated": evaluated,
        "candidate_regimes": dict(
            sorted((diagnostics.get("candidate_regimes") or {}).items())
        ),
        "cumulative_stage_counts": {
            stage: int((diagnostics.get("stage_counts") or {}).get(stage, 0))
            for stage in _DIRECTIONAL_FUNNEL_STAGES
        },
        "cumulative_stage_percent_of_candidates": {
            stage: round(
                int((diagnostics.get("stage_counts") or {}).get(stage, 0))
                / candidates
                * 100,
                2,
            )
            if candidates
            else 0.0
            for stage in _DIRECTIONAL_FUNNEL_STAGES
        },
        "independent_condition_pass_counts": {
            stage: int(
                (diagnostics.get("condition_pass_counts") or {}).get(stage, 0)
            )
            for stage in _DIRECTIONAL_FUNNEL_STAGES
        },
        "first_failure_counts": dict(
            sorted((diagnostics.get("first_failure_counts") or {}).items())
        ),
        "confirmed_candidate_score_distributions": {
            name: _serialize_score_distribution(distribution)
            for name, distribution in sorted(
                (
                    diagnostics.get("confirmed_candidate_score_distributions")
                    or {}
                ).items()
            )
        },
        "master_candidate_chain_audit": _serialize_master_candidate_chain_audit(
            diagnostics.get("master_candidate_chain_audit") or {}
        ),
        "contract": {
            "scope": "READ_ONLY_DIAGNOSTIC",
            "candidate_denominator": candidates,
            "stage_order": list(_DIRECTIONAL_FUNNEL_STAGES),
            "first_failures_reconcile_to_candidates": (
                sum((diagnostics.get("first_failure_counts") or {}).values())
                + int(
                    (diagnostics.get("stage_counts") or {}).get(
                        "FINAL_ELIGIBLE",
                        0,
                    )
                )
                == candidates
            ),
        },
    }


def _update_master_candidate_chain_audit(diagnostics, audit):
    master_signal = dict(audit.get("master_signal") or {})
    contradiction = dict(audit.get("contradiction") or {})
    risk = dict(audit.get("risk") or {})
    executor = dict(audit.get("executor") or {})
    diagnostics["evaluated"] += 1
    diagnostics["contradiction_statuses"][
        str(contradiction.get("status") or "UNKNOWN")
    ] += 1
    diagnostics["contradiction_trade_allowed"][
        "ALLOWED" if contradiction.get("trade_allowed") else "BLOCKED"
    ] += 1
    _update_score_distribution(
        diagnostics["conflict_scores"],
        contradiction.get("conflict_score"),
    )
    _update_score_distribution(
        diagnostics["master_signal_scores"],
        master_signal.get("score"),
    )
    _update_score_distribution(
        diagnostics["master_signal_confidences"],
        master_signal.get("confidence"),
    )
    _update_score_distribution(
        diagnostics["risk_confidences"],
        risk.get("confidence"),
    )
    for conflict in contradiction.get("conflicts") or ():
        diagnostics["conflict_names"][str(conflict.get("name") or "UNKNOWN")] += 1
        diagnostics["conflict_severities"][
            str(conflict.get("severity") or "UNKNOWN")
        ] += 1
    for source, value in (contradiction.get("bias_map") or {}).items():
        diagnostics["bias_maps"].setdefault(source, Counter())[str(value)] += 1
    diagnostics["risk_decisions"][str(risk.get("decision") or "UNKNOWN")] += 1
    diagnostics["risk_reasons"][str(risk.get("reason") or "UNKNOWN")] += 1
    diagnostics["executor_verdicts"][
        str(executor.get("verdict") or "UNKNOWN")
    ] += 1
    diagnostics["current_price_availability"][
        "PRESENT" if audit.get("current_price_available") else "MISSING"
    ] += 1


def _serialize_master_candidate_chain_audit(diagnostics):
    return {
        "evaluated": int(diagnostics.get("evaluated") or 0),
        "contradiction_statuses": dict(
            sorted((diagnostics.get("contradiction_statuses") or {}).items())
        ),
        "contradiction_trade_allowed": dict(
            sorted((diagnostics.get("contradiction_trade_allowed") or {}).items())
        ),
        "conflict_score_distribution": _serialize_score_distribution(
            diagnostics.get("conflict_scores") or _new_score_distribution()
        ),
        "master_signal_score_distribution": _serialize_score_distribution(
            diagnostics.get("master_signal_scores") or _new_score_distribution()
        ),
        "master_signal_confidence_distribution": _serialize_score_distribution(
            diagnostics.get("master_signal_confidences") or _new_score_distribution()
        ),
        "risk_confidence_distribution": _serialize_score_distribution(
            diagnostics.get("risk_confidences") or _new_score_distribution()
        ),
        "conflict_names": dict(
            sorted((diagnostics.get("conflict_names") or {}).items())
        ),
        "conflict_severities": dict(
            sorted((diagnostics.get("conflict_severities") or {}).items())
        ),
        "bias_maps": {
            source: dict(sorted(values.items()))
            for source, values in sorted(
                (diagnostics.get("bias_maps") or {}).items()
            )
        },
        "risk_decisions": dict(
            sorted((diagnostics.get("risk_decisions") or {}).items())
        ),
        "risk_reasons": dict(
            sorted((diagnostics.get("risk_reasons") or {}).items())
        ),
        "executor_verdicts": dict(
            sorted((diagnostics.get("executor_verdicts") or {}).items())
        ),
        "current_price_availability": dict(
            sorted((diagnostics.get("current_price_availability") or {}).items())
        ),
        "scope": "READ_ONLY_MASTER_CANDIDATES_AFTER_TIMEFRAME_GATE",
    }


def _stateful_regime_from_stack(stack_context):
    if not isinstance(stack_context, dict) or stack_context.get("status") != "READY":
        return None
    decision_timeframe = str(stack_context.get("decision_chain_timeframe") or "")
    if not decision_timeframe:
        return None
    record = next(
        (
            item
            for item in (stack_context.get("timeframes") or ())
            if str(item.get("timeframe") or "") == decision_timeframe
        ),
        None,
    )
    intelligence = record.get("intelligence") if isinstance(record, dict) else None
    regime = intelligence.get("regime") if isinstance(intelligence, dict) else None
    if not isinstance(regime, dict) or not regime.get("regime"):
        return None
    try:
        confidence = float(regime.get("confidence"))
    except (TypeError, ValueError):
        return None
    return {**regime, "confidence": confidence}


def _timeframe_stack_gate(
    stack_context,
    requested_side,
    *,
    enforce_decision_chain=True,
):
    if stack_context is None:
        return 0, []
    if not isinstance(stack_context, dict) or stack_context.get("status") != "READY":
        return 0, ["TIMEFRAME_STACK_UNAVAILABLE"]

    timeframes = list(stack_context.get("timeframes") or [])
    confirmation = dict(stack_context.get("confirmation") or {})
    if len(timeframes) != len(OFFICIAL_ENTRY_TIMEFRAMES):
        return 0, ["TIMEFRAME_STACK_UNAVAILABLE"]

    higher_bias = str(timeframes[-1].get("bias") or "").upper()
    if requested_side == "LONG" and higher_bias in BEARISH_BIASES:
        return 0, ["HIGHER_TIMEFRAME_CONFLICT"]
    if requested_side == "SHORT" and higher_bias in BULLISH_BIASES:
        return 0, ["HIGHER_TIMEFRAME_CONFLICT"]

    permission = str(confirmation.get("trade_permission") or "").upper()
    if requested_side == "LONG" and permission in {"SHORT_ONLY", "SHORT_ALLOWED"}:
        return 0, ["TIMEFRAME_PERMISSION_CONFLICT"]
    if requested_side == "SHORT" and permission in {"LONG_ONLY", "LONG_ALLOWED"}:
        return 0, ["TIMEFRAME_PERMISSION_CONFLICT"]

    stack_state = str(confirmation.get("stack_state") or "").upper()
    if stack_state == "MIXED_STRONG":
        return 0, ["TIMEFRAME_STACK_STRONG_CONFLICT"]

    decision_chain = stack_context.get("decision_chain")
    if enforce_decision_chain and isinstance(decision_chain, dict):
        chain_signal = str(
            (decision_chain.get("signal") or {}).get("signal") or ""
        ).upper()
        if chain_signal not in {"LONG", "SHORT"}:
            return 0, ["REPLAY_SIGNAL_NOT_ACTIONABLE"]
        if chain_signal != requested_side:
            return 0, ["REPLAY_SIGNAL_SIDE_MISMATCH"]

        contradiction = dict(decision_chain.get("contradiction") or {})
        if not contradiction.get("trade_allowed"):
            return 0, ["CONTRADICTION_GATE_BLOCKED"]

        risk = dict(decision_chain.get("risk") or {})
        if str(risk.get("decision") or "").upper() != "APPROVE":
            return 0, ["RISK_GATE_REJECTED"]

        executor = dict(decision_chain.get("executor") or {})
        if str(executor.get("verdict") or "").upper() != "WOULD_QUEUE":
            return 0, ["EXECUTOR_NOT_READY"]

    return 0, []


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


def _decision_timestamp(candle):
    return (
        getattr(candle, "close_time", None)
        or getattr(candle, "candle_time", None)
        or getattr(candle, "open_time", None)
    )


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


def _percentage_distribution(counts, total):
    if not total:
        return {}
    return {
        key: round((value / total) * 100, 2)
        for key, value in sorted(counts.items())
    }


def _new_score_distribution(*, signed=False):
    return {
        "count": 0,
        "value_sum": 0.0,
        "minimum": None,
        "maximum": None,
        "buckets": Counter(),
        "signed": bool(signed),
    }


def _update_score_distribution(distribution, value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return
    distribution["count"] += 1
    distribution["value_sum"] += numeric
    distribution["minimum"] = (
        numeric
        if distribution["minimum"] is None
        else min(distribution["minimum"], numeric)
    )
    distribution["maximum"] = (
        numeric
        if distribution["maximum"] is None
        else max(distribution["maximum"], numeric)
    )
    if distribution.get("signed"):
        lower = min(90, max(-100, int(numeric // 10) * 10))
        if lower < 0:
            label = f"NEG_{abs(lower):02d}_{abs(lower + 9):02d}"
        elif lower == 0:
            label = "ZERO_09"
        else:
            label = f"POS_{lower:02d}_{'100' if lower == 90 else f'{lower + 9:02d}'}"
    else:
        lower = min(90, max(0, int(numeric // 10) * 10))
        label = f"{lower:02d}-{'100' if lower == 90 else f'{lower + 9:02d}'}"
    distribution["buckets"][label] += 1


def _serialize_score_distribution(distribution):
    count = int(distribution["count"])
    return {
        "count": count,
        "minimum": (
            round(distribution["minimum"], 4)
            if distribution["minimum"] is not None
            else None
        ),
        "maximum": (
            round(distribution["maximum"], 4)
            if distribution["maximum"] is not None
            else None
        ),
        "average": (
            round(distribution["value_sum"] / count, 4) if count else None
        ),
        "value_sum": round(distribution["value_sum"], 6),
        "buckets": dict(sorted(distribution["buckets"].items())),
    }


def _new_master_signal_diagnostics():
    return {
        "evaluated": 0,
        "signals": Counter(),
        "biases": Counter(),
        "score_distribution": _new_score_distribution(signed=True),
        "components": {},
    }


def _update_master_signal_diagnostics(diagnostics, decision):
    stack = decision.get("timeframe_stack") or {}
    chain = stack.get("decision_chain") or {}
    signal = chain.get("signal") or {}
    if not signal:
        return
    diagnostics["evaluated"] += 1
    diagnostics["signals"][str(signal.get("signal") or "UNKNOWN")] += 1
    diagnostics["biases"][str(signal.get("bias") or "UNKNOWN")] += 1
    _update_score_distribution(diagnostics["score_distribution"], signal.get("score"))
    profile = signal.get("scoring_profile") or {}
    for component in profile.get("components") or ():
        name = str(component.get("name") or "UNKNOWN")
        aggregate = diagnostics["components"].setdefault(
            name,
            {
                "values": Counter(),
                "score_distribution": _new_score_distribution(signed=True),
            },
        )
        aggregate["values"][str(component.get("value") or "NONE")] += 1
        _update_score_distribution(
            aggregate["score_distribution"],
            component.get("score"),
        )


def _serialize_master_signal_diagnostics(diagnostics):
    return {
        "evaluated": diagnostics["evaluated"],
        "signals": dict(sorted(diagnostics["signals"].items())),
        "biases": dict(sorted(diagnostics["biases"].items())),
        "score_distribution": _serialize_score_distribution(
            diagnostics["score_distribution"]
        ),
        "components": {
            name: {
                "values": dict(sorted(component["values"].items())),
                "score_distribution": _serialize_score_distribution(
                    component["score_distribution"]
                ),
            }
            for name, component in sorted(diagnostics["components"].items())
        },
    }


def _independent_gate_passes(blocked_reasons):
    blocked = set(blocked_reasons)
    families = {
        "MARKET_DATA": lambda reason: reason == "ATR_UNAVAILABLE",
        "CONFIDENCE": lambda reason: reason.startswith("CONFIDENCE_"),
        "TREND": lambda reason: reason.startswith("TREND_"),
        "MOMENTUM": lambda reason: reason.startswith("MOMENTUM_"),
        "FEATURE_SIGNAL": lambda reason: reason.startswith("FEATURE_SIGNAL_"),
        "REGIME": lambda reason: reason.startswith("REGIME_")
        or reason.startswith("BEAR_RALLY_"),
        "TIMEFRAME_ALIGNMENT": lambda reason: reason
        in {
            "TIMEFRAME_STACK_UNAVAILABLE",
            "HIGHER_TIMEFRAME_CONFLICT",
            "TIMEFRAME_PERMISSION_CONFLICT",
            "TIMEFRAME_STACK_STRONG_CONFLICT",
        },
        "DECISION_CHAIN": lambda reason: reason.startswith("REPLAY_")
        or reason
        in {
            "CONTRADICTION_GATE_BLOCKED",
            "RISK_GATE_REJECTED",
            "EXECUTOR_NOT_READY",
        },
    }
    passed = [
        family
        for family, matches in families.items()
        if not any(matches(reason) for reason in blocked)
    ]
    if not blocked:
        passed.append("ALL_PRE_ENTRY_GATES")
    return passed


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
