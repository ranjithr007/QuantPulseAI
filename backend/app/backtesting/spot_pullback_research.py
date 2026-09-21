"""Isolated OHLCV research. No database, registry, scheduler or order adapter.

All timestamps are UTC bar OPEN times. Signals are indexed by availability time
(bar close), so an hourly candle can never leak into its constituent 15m bars.
This is a deliberately incomplete execution model, never a promotion authority.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math

import numpy as np
import pandas as pd


VERSION = "SPOT_TREND_PULLBACK_RESEARCH_V1"
BAR = pd.Timedelta(minutes=15)
LIMITATIONS = [
    "Exploratory historical screen; not an untouched holdout or live approval.",
    "OHLCV cannot validate spread, depth, five-second limit fills or partial fills.",
    "No point-in-time news/calendar veto; no historical exchange lot/tick metadata.",
    "Fixed research symbols; no reconstructed monthly top-20 universe or listing-age gate.",
    "Intrabar portfolio low marks are conservative synchronized-low scenarios, not observed paths.",
    "No live/paper scheduler registration; forward validation and promotion remain disabled.",
]


@dataclass(frozen=True)
class ResearchConfig:
    initial_equity: float = 10_000.0
    risk_fraction: float = 0.0025
    fee_bps: float = 10.0
    execution_bps: float = 5.0  # combined adverse half-spread/slippage, each side
    entry_delay_bars: int = 0

    def __post_init__(self):
        if not all(math.isfinite(x) for x in (
            self.initial_equity, self.risk_fraction, self.fee_bps, self.execution_bps
        )):
            raise ValueError("Configuration must be finite")
        if self.initial_equity <= 0 or not 0 < self.risk_fraction <= 0.0025:
            raise ValueError("Positive equity and risk <= 0.25% required")
        if not 0 <= self.fee_bps <= 100 or not 0 <= self.execution_bps <= 100:
            raise ValueError("Costs must be between 0 and 100 bps per side")
        if type(self.entry_delay_bars) is not int or self.entry_delay_bars not in (0, 1):
            raise ValueError("Only baseline or one-bar delayed sensitivity is supported")


def validate_candles(frame):
    required = ["open", "high", "low", "close", "quote_volume"]
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Candles require a timezone-aware DatetimeIndex")
    frame = frame.copy()
    frame.index = frame.index.tz_convert("UTC")
    if frame.empty or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("Candles must be nonempty, ordered and unique")
    if not frame.index.equals(frame.index.floor("15min")):
        raise ValueError("Candles must align to UTC 15-minute opens")
    if len(frame) > 1 and not (frame.index.to_series().diff().iloc[1:] == BAR).all():
        raise ValueError("Missing candles: repair source data; never forward-fill OHLCV")
    if not set(required).issubset(frame.columns):
        raise ValueError("Missing OHLCV columns")
    frame[required] = frame[required].astype(float)
    if not np.isfinite(frame[required].to_numpy()).all():
        raise ValueError("Nonfinite candle values")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Prices must be positive")
    if (frame.quote_volume < 0).any():
        raise ValueError("Volume must be nonnegative")
    if ((frame.high < frame[["open", "close", "low"]].max(axis=1)) |
            (frame.low > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC envelope")
    return frame[required]


def seeded_average(series, period, alpha):
    """Explicit SMA seed; no pandas EWM first-observation seed drift."""
    values = np.full(len(series), np.nan)
    if len(series) >= period:
        values[period - 1] = float(series.iloc[:period].mean())
        source = series.to_numpy()
        for i in range(period, len(series)):
            values[i] = alpha * source[i] + (1 - alpha) * values[i - 1]
    return pd.Series(values, index=series.index)


def indicators(frame):
    out = frame.copy()
    for n in (20, 50, 200):
        out[f"ema{n}"] = seeded_average(out.close, n, 2 / (n + 1))
    previous = out.close.shift()
    tr = pd.concat([out.high - out.low, (out.high - previous).abs(),
                    (out.low - previous).abs()], axis=1).max(axis=1)
    out["atr"] = seeded_average(tr, 14, 1 / 14)
    return out


def hourly_context(frame):
    hourly = frame.resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "quote_volume": "sum",
    })
    counts = frame.close.resample("1h").count()
    hourly = indicators(hourly.loc[counts == 4])
    hourly.index = hourly.index + pd.Timedelta(hours=1)
    hourly["trend"] = ((hourly.close > hourly.ema50) &
                       (hourly.ema50 > hourly.ema200) &
                       (hourly.ema50 > hourly.ema50.shift(5)))
    ratio = hourly.atr / hourly.close
    threshold = ratio.shift().rolling(90 * 24, min_periods=90 * 24).quantile(.95)
    hourly["volatility_ok"] = ratio <= threshold
    hourly["ready"] = np.arange(len(hourly)) >= 999
    return hourly


def build_features(frame, btc_frame=None):
    """Features available after each completed bar; index is decision time."""
    frame = validate_candles(frame)
    out = indicators(frame)
    prior_touch = (out.low <= out.ema20).shift().rolling(3).max() == 1
    prior_support = (out.close > out.ema50).shift().rolling(3).min() == 1
    out["setup"] = (prior_touch & prior_support & (out.close > out.ema20) &
                    (out.close > out.open) & (out.close > out.high.shift()) &
                    (out.quote_volume >= 1.2 * out.quote_volume.shift().rolling(20).median()))
    out["stop"] = out.low.rolling(4).min() - .25 * out.atr
    out["turnover"] = frame.quote_volume.resample("1D").sum().shift().rolling(30).median().reindex(
        out.index.floor("D")).to_numpy()
    out.index = out.index + BAR
    context = hourly_context(frame).reindex(out.index, method="ffill")
    out["trend"] = context.trend.eq(True)
    out["trend_exit"] = context.close < context.ema50
    out["volatility_ok"] = context.volatility_ok.eq(True)
    out["signal"] = (out.setup & out.trend & out.volatility_ok &
                     context.ready.eq(True) &
                     (np.arange(len(out)) >= 199) & (out.turnover >= 50_000_000))
    if btc_frame is not None:
        btc = hourly_context(validate_candles(btc_frame)).reindex(out.index, method="ffill")
        out["signal"] &= btc.close > btc.ema200
    return out


def entry_plan(signal, raw_open, equity, cash, open_risk, config, gross_exposure=0):
    fee, slip = config.fee_bps / 10_000, config.execution_bps / 10_000
    entry = raw_open * (1 + slip)
    stop, atr = float(signal["stop"]), float(signal["atr"])
    distance = entry - stop
    if not all(math.isfinite(v) for v in (entry, stop, atr, equity, cash, open_risk)):
        return None, "NONFINITE_PLAN"
    if atr <= 0 or stop <= 0 or not atr <= distance <= signal.get("max_stop_atr", 2.5) * atr or distance / entry > .03:
        return None, "STOP_DISTANCE"
    if entry > float(signal["close"]) + signal.get("entry_cap_atr", .1) * atr:
        return None, "ENTRY_PRICE_CAP"
    # Conservative allowance counts modeled execution costs on BOTH sides, even
    # though the entry fill already includes its adverse move.
    costs = 2 * entry * (fee + slip)
    if costs > .15 * distance:
        return None, "COST_TO_RISK"
    target = signal.get("fixed_target", entry + 1.5 * distance)
    if "fixed_target" in signal and (not math.isfinite(target) or target <= entry or
                                      (target - entry - costs) / (distance + costs) < 1.5):
        return None, "NET_REWARD_RISK"
    budget = min(equity * config.risk_fraction, max(0, equity * .005 - open_risk))
    quantity = min(budget / (distance + costs), .25 * equity / entry,
                   cash / (entry * (1 + fee)), .001 * signal["quote_volume"] / entry)
    if "fixed_target" in signal:
        quantity = min(quantity, max(0, .50 * equity - gross_exposure) / entry)
    if quantity <= 0:
        return None, "CAPACITY"
    return {"entry": entry, "stop": stop, "target": target,
            "quantity": quantity, "risk_budget": quantity * (distance + costs),
            "entry_fee": quantity * entry * fee, "atr": atr,
            "signal_close": float(signal["close"]),
            "signal_quote_volume": float(signal["quote_volume"]),
            "max_hold_hours": signal.get("max_hold_hours", 6),
            "regime_exit_reason": signal.get("regime_exit_reason", "TREND_EXIT")}, None


def exit_trigger(position, bar, now, trend_exit=False):
    """Gap stops first; open-time exits precede subsequent bar extrema."""
    if bar["open"] <= position["stop"]:
        return "STOP", bar["open"], now
    if trend_exit:
        return position.get("regime_exit_reason", "TREND_EXIT"), bar["open"], now
    if now >= position["entry_time"] + pd.Timedelta(hours=position.get("max_hold_hours", 6)):
        return "TIME_EXIT", bar["open"], now
    if bar["low"] <= position["stop"]:
        return "STOP", position["stop"], now + BAR
    if bar["high"] >= position["target"]:
        return "TARGET", position["target"], now + BAR
    return None


def review_loss(trade, version=VERSION):
    """Evidence rules, not an LLM causal assertion or live policy writer."""
    if trade["exit_reason"] != "STOP":
        return None
    gap = trade["exit_reference"] < trade["stop"]
    return {
        "symbol": trade["symbol"], "entry_time": trade["entry_time"],
        "exit_time": trade["exit_time"], "strategy_version": version,
        "classification": "ADVERSE_GAP_OBSERVED" if gap else "ORDINARY_LOSS_OR_UNKNOWN",
        "causal_confidence": "UNDETERMINED",
        "evidence": {k: trade[k] for k in (
            "entry", "stop", "atr", "exit_reference", "exit", "fees", "net_pnl",
            "signal_close", "signal_quote_volume")},
        "unavailable": ["news causation", "historical spread/depth", "order rejection logs"],
        "recommendation": "Accumulate comparable cases; test gap-risk veto at equal risk."
        if gap else "Retain frozen rules; compare stopped trades with all other outcomes.",
        "automatic_live_change_allowed": False,
        "candidate_status": "INSUFFICIENT_EVIDENCE",
    }


def run_screen(candles, *, start, end, config=None, policy=None, tradable_symbols=None):
    """One shared cash account, [start,end), warm-up supplied before start.

    Risk latches are never reset within a run after weekly loss or drawdown.
    A restart is a new research experiment, never an automatic operational reset.
    """
    config = config or ResearchConfig()
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Provide ordered timezone-aware start/end")
    start, end = start.tz_convert("UTC"), end.tz_convert("UTC")
    if start != start.floor("15min") or end != end.floor("15min"):
        raise ValueError("Evaluation boundaries must align to 15 minutes")
    if not candles or "BTCUSDT" not in candles:
        raise ValueError("BTCUSDT required for market context")
    clean = {symbol: validate_candles(frame) for symbol, frame in sorted(candles.items())}
    tradable = sorted(clean) if tradable_symbols is None else list(tradable_symbols)
    if not tradable or len(set(tradable)) != len(tradable) or not set(tradable).issubset(clean):
        raise ValueError("Tradable symbols must be distinct, nonempty and present in inputs")
    tradable = sorted(tradable)
    timeline = pd.date_range(start, end, freq="15min", inclusive="left")
    for symbol, frame in clean.items():
        if not timeline.isin(frame.index).all():
            raise ValueError(f"{symbol}: incomplete evaluation coverage")
    if policy is None:
        version = VERSION
        features = {s: build_features(f, clean["BTCUSDT"] if s != "BTCUSDT" else None)
                    for s, f in clean.items()}
    elif policy == {"id": "SPOT_RANGE_REVERSION_HYPOTHESIS_V1"}:
        from app.backtesting.spot_range_reversion import build_range_features
        version = policy["id"]
        features = {s: build_range_features(f) for s, f in clean.items()}
    else:
        from app.backtesting.spot_pullback_comparison import build_policy_features, validate_policy
        validate_policy(policy)
        version = "SPOT_COMPARISON_V1_" + policy["id"]
        features = {s: build_policy_features(f, clean["BTCUSDT"] if s != "BTCUSDT" else None, policy)
                    for s, f in clean.items()}
    bars = {s: f.to_dict("index") for s, f in clean.items()}
    decisions = {s: f.to_dict("index") for s, f in features.items()}
    cash = peak = day_start = week_start = config.initial_equity
    positions, cooldown = {}, {}
    trades, equity_curve, daily, risk_events = [], [], [], []
    blocked = Counter()
    day = week = None
    daily_entries = consecutive_stops = 0
    daily_halt = permanent_halt = False
    fee, slip = config.fee_bps / 10_000, config.execution_bps / 10_000

    def mark(prices):
        return cash + sum(p["quantity"] * prices[s] * (1 - slip) * (1 - fee)
                          for s, p in positions.items())

    def close_position(symbol, raw, reason, when):
        nonlocal cash, consecutive_stops
        p = positions.pop(symbol)
        fill = raw * (1 - slip)
        exit_fee = fill * p["quantity"] * fee
        cash += fill * p["quantity"] - exit_fee
        pnl = (fill - p["entry"]) * p["quantity"] - exit_fee - p["entry_fee"]
        trade = {**p, "symbol": symbol, "exit": fill, "exit_reference": raw,
                 "exit_reason": reason, "exit_time": when.isoformat(),
                 "entry_time": p["entry_time"].isoformat(), "net_pnl": pnl,
                 "fees": p["entry_fee"] + exit_fee, "net_r": pnl / p["risk_budget"]}
        trades.append(trade)
        if reason == "STOP":
            cooldown[symbol] = when + pd.Timedelta(hours=1)
            consecutive_stops += 1
        else:
            consecutive_stops = 0

    def risk_breach(equity, now):
        nonlocal daily_halt, permanent_halt
        reason = None
        if equity <= peak * .95:
            reason, permanent_halt = "DRAWDOWN_HALT", True
        elif equity <= week_start * .97:
            reason, permanent_halt = "WEEKLY_HALT", True
        elif equity <= day_start * .99:
            reason, daily_halt = "DAILY_HALT", True
        if reason and (not risk_events or risk_events[-1]["reason"] != reason):
            risk_events.append({"time": now.isoformat(), "reason": reason, "equity": equity})
        return reason

    for now in timeline:
        opened = {s: bars[s][now]["open"] for s in clean}
        opening_equity = mark(opened)
        if day != now.date():
            if day is not None:
                daily.append({"date": str(day), "return": (opening_equity / day_start - 1),
                              "equity": opening_equity})
            day, day_start = now.date(), opening_equity
            daily_entries, consecutive_stops, daily_halt = 0, 0, False
        this_week = (now.isocalendar().year, now.isocalendar().week)
        if week != this_week:
            week, week_start = this_week, opening_equity
        peak = max(peak, opening_equity)
        opening_breach = risk_breach(opening_equity, now)
        if opening_breach:
            for s in list(positions):
                close_position(s, opened[s], opening_breach, now)

        # Open-time exits are processed before admissions; intrabar exits after.
        for s in list(positions):
            bar = bars[s][now]
            feature = decisions[s].get(now, {})
            trigger = exit_trigger(positions[s], {**bar, "low": bar["open"], "high": bar["open"]},
                                   now, feature.get("trend_exit", False))
            if trigger:
                close_position(s, trigger[1], trigger[0], now)
        if consecutive_stops >= 3:
            daily_halt = True

        candidates = []
        for s in tradable:
            at = now - config.entry_delay_bars * BAR
            signal = decisions[s].get(at)
            if signal and signal["signal"]:
                candidates.append((s, signal, at))
        candidates.sort(key=lambda item: (-item[1]["turnover"], item[0]))
        for s, signal, signal_time in candidates:
            if permanent_halt or daily_halt:
                blocked["RISK_HALT"] += 1
                continue
            if s in positions or len(positions) >= 2 or daily_entries >= 3:
                blocked["POSITION_OR_DAILY_CAP"] += 1
                continue
            if signal_time <= cooldown.get(s, pd.Timestamp.min.tz_localize("UTC")):
                blocked["STOP_COOLDOWN"] += 1
                continue
            equity = mark(opened)
            gross = sum(p["quantity"] * opened[k] for k, p in positions.items())
            plan, reason = entry_plan(signal, opened[s], equity, cash,
                                      sum(p["risk_budget"] for p in positions.values()), config, gross)
            if plan is None:
                blocked[reason] += 1
                continue
            if gross + plan["quantity"] * plan["entry"] > equity * .50:
                blocked["GROSS_EXPOSURE"] += 1
                continue
            plan.update(entry_time=now, signal_time=signal_time.isoformat())
            cash -= plan["quantity"] * plan["entry"] + plan["entry_fee"]
            positions[s] = plan
            daily_entries += 1

        # Mark adverse extremes before targets; a stop caps the modeled path
        # only after accounting for its opening gap. This is conservative OHLC.
        adverse = {s: max(bars[s][now]["low"], min(opened[s], p["stop"]))
                   for s, p in positions.items()}
        low_equity = mark(adverse)
        peak = max(peak, mark(opened))
        equity_curve.append({"time": now.isoformat(), "equity": low_equity,
                             "kind": "CONSERVATIVE_INTRABAR_LOW"})
        breach = risk_breach(low_equity, now)
        if breach:
            for s in list(positions):
                close_position(s, adverse[s], breach, now + BAR)
        else:
            for s in list(positions):
                trigger = exit_trigger(positions[s], bars[s][now], now)
                if trigger:
                    close_position(s, trigger[1], trigger[0], trigger[2])
        if consecutive_stops >= 3:
            daily_halt = True
        closing = {s: bars[s][now]["close"] for s in clean}
        equity = mark(closing)
        peak = max(peak, equity)
        equity_curve.append({"time": (now + BAR).isoformat(), "equity": equity, "kind": "CLOSE"})
        risk_breach(equity, now + BAR)

    # Explicit liquidation, not silent omission of open losing trades.
    last = timeline[-1]
    for s in list(positions):
        close_position(s, bars[s][last]["close"], "END_OF_SAMPLE", end)
    daily.append({"date": str(day), "return": cash / day_start - 1, "equity": cash})
    metrics = summarize(trades, equity_curve, config.initial_equity, cash)
    return {
        "strategy_version": version, "mode": "OFFLINE_OHLCV_RESEARCH_ONLY",
        "signal_policy": dict(policy) if policy is not None else None,
        "live_execution_enabled": False, "promotion_allowed": False,
        "config": asdict(config), "config_hash": sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest(),
        "start": start.isoformat(), "end_exclusive": end.isoformat(),
        "symbols": tradable, "context_input_symbols": list(clean), "limitations": LIMITATIONS,
        "metrics": metrics, "trades": trades, "daily_returns": daily,
        "equity_curve": equity_curve, "blocked_signals": dict(blocked), "risk_events": risk_events,
        "loss_reviews": [review_loss(t, version) for t in trades if t["exit_reason"] == "STOP"],
        "evidence_status": "INSUFFICIENT_FOR_PROMOTION",
        "observed_metric_gates": {
            "positive_expectancy": metrics["expectancy_quote"] is not None and metrics["expectancy_quote"] > 0,
            "profit_factor_1_25": metrics["profit_factor"] is not None and metrics["profit_factor"] >= 1.25,
            "drawdown_at_most_5_percent": metrics["max_drawdown_percent"] <= 5,
            "500_completed_trades": len(trades) >= 500,
        },
    }


def summarize(trades, curve, initial, final):
    pnl = [t["net_pnl"] for t in trades]
    wins = sum(x > 0 for x in pnl)
    profit, loss = sum(max(x, 0) for x in pnl), -sum(min(x, 0) for x in pnl)
    peak, drawdown = initial, 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, 1 - point["equity"] / peak)
    # Descriptive only: dependence and selection invalidate standalone claims.
    lower = None
    if pnl:
        n, z, p = len(pnl), 1.6448536269514722, wins / len(pnl)
        lower = (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / (1+z*z/n)
    return {"closed_trades": len(pnl), "wins": wins,
            "net_win_rate_percent": wins / len(pnl) * 100 if pnl else None,
            "iid_wilson_95_one_sided_lower_percent": lower * 100 if lower is not None else None,
            "win_rate_above_80_validated": False,
            "net_pnl": final - initial, "return_percent": (final / initial - 1) * 100,
            "profit_factor": profit / loss if loss else None,
            "expectancy_quote": sum(pnl) / len(pnl) if pnl else None,
            "expectancy_r": sum(t["net_r"] for t in trades) / len(trades) if trades else None,
            "max_drawdown_percent": drawdown * 100,
            "fees": sum(t["fees"] for t in trades)}
