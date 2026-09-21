"""Preregistered research variants; no operational strategy registration."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtesting.spot_pullback_research import BAR, indicators, validate_candles


def validate_policy(policy):
    if set(policy) != {"id", "entry_minutes", "context_hours", "entry_cap_atr", "max_hold_hours", "setup"}:
        raise ValueError("Unexpected or missing policy fields")
    if (policy["entry_minutes"], policy["context_hours"], policy["max_hold_hours"]) not in ((15, 1, 6), (60, 4, 24)):
        raise ValueError("Unsupported preregistered horizon")
    if policy["entry_cap_atr"] not in (.1, .5) or policy["setup"] not in ("pullback", "trend_transition"):
        raise ValueError("Unsupported cap or setup")
    if not isinstance(policy["id"], str) or not policy["id"]:
        raise ValueError("A distinct policy identifier is required")


def aggregate(frame, minutes):
    """Discard incomplete edge candles; never synthesize missing observations."""
    rule = f"{minutes}min"
    count = frame.close.resample(rule).count()
    out = frame.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                   "close": "last", "quote_volume": "sum"})
    return out.loc[count == minutes // 15]


def context(frame, hours):
    out = indicators(aggregate(frame, hours * 60))
    out.index += pd.Timedelta(hours=hours)
    out["trend"] = (out.close > out.ema50) & (out.ema50 > out.ema200) & (out.ema50 > out.ema50.shift(5))
    ratio = out.atr / out.close
    window = 90 * 24 // hours
    out["volatility_ok"] = ratio <= ratio.shift().rolling(window).quantile(.95)
    out["ready"] = np.arange(len(out)) >= 999
    return out


def build_policy_features(frame, btc_frame, policy):
    validate_policy(policy)
    frame = validate_candles(frame)
    minutes, hours = policy["entry_minutes"], policy["context_hours"]
    coarse = aggregate(frame, minutes)
    out = indicators(coarse)
    touched = (out.low <= out.ema20).shift().rolling(3).max().eq(1)
    support = (out.close > out.ema50).shift().rolling(3).min().eq(1)
    out["setup"] = (touched & support & (out.close > out.ema20) &
                    (out.close > out.open) & (out.close > out.high.shift()) &
                    (out.quote_volume >= 1.2 * out.quote_volume.shift().rolling(20).median()))
    out["stop"] = out.low.rolling(4).min() - .25 * out.atr
    out["turnover"] = frame.quote_volume.resample("1D").sum().shift().rolling(30).median().reindex(
        out.index.floor("D")).to_numpy()
    out.index += pd.Timedelta(minutes=minutes)
    trend = context(frame, hours).reindex(out.index, method="ffill")
    out["trend"] = trend.trend.eq(True)
    out["trend_exit"] = trend.close < trend.ema50
    out["volatility_ok"] = trend.volatility_ok.eq(True)
    if policy["setup"] == "trend_transition":
        out["setup"] = out.trend & ~out.trend.shift(fill_value=False)
        out["stop"] = out.close - 2 * out.atr
    out["signal"] = (out.setup & out.trend & out.volatility_ok & trend.ready.eq(True) &
                     (np.arange(len(out)) >= 199) & (out.turnover >= 50_000_000))
    if btc_frame is not None:
        btc = context(validate_candles(btc_frame), hours).reindex(out.index, method="ffill")
        out["signal"] &= btc.close > btc.ema200
    # Liquidity capacity still uses the last 15m turnover, not an entire hour.
    available = frame.copy()
    available.index += BAR
    out["quote_volume"] = available.quote_volume.reindex(out.index)
    out["entry_cap_atr"] = policy["entry_cap_atr"]
    out["max_hold_hours"] = policy["max_hold_hours"]
    # Preserve close-time event exits between signal bars but never reuse an
    # already-consumed hourly entry signal on the next 15m execution step.
    fine_index = available.index
    expanded = out.reindex(fine_index, method="ffill")
    expanded["signal"] = out.signal.reindex(fine_index, fill_value=False)
    expanded["trend_exit"] = expanded.trend_exit.eq(True)
    return expanded


def diagnostics(result):
    by_symbol = {}
    for symbol in result["symbols"]:
        trades = [t for t in result["trades"] if t["symbol"] == symbol]
        by_symbol[symbol] = {"trades": len(trades), "net_pnl": sum(t["net_pnl"] for t in trades)}
    years = {}
    for row in result["daily_returns"]:
        year = row["date"][:4]
        years[year] = (1 + years.get(year, 0)) * (1 + row["return"]) - 1
    values = np.array([r["return"] for r in result["daily_returns"]])
    # Circular moving weekly blocks; all symbols already share one daily return.
    # Descriptive only: nonstationarity, selection and small samples remain.
    rng = np.random.default_rng(20260921)
    samples = []
    for _ in range(2000):
        starts = rng.integers(0, len(values), size=(len(values) + 6) // 7)
        indices = ((starts[:, None] + np.arange(7)) % len(values)).ravel()[:len(values)]
        samples.append(float(values[indices].mean()))
    return {"by_symbol": by_symbol, "calendar_year_returns_percent": {k: v * 100 for k, v in years.items()},
            "weekly_block_daily_mean_95_interval_percent": (np.quantile(samples, [.025, .975]) * 100).tolist(),
            "bootstrap_note": "Descriptive; not selection-adjusted, not proof of positive trade expectancy.",
            "first_failure_counts": result["blocked_signals"]}


def buy_hold(candles, start, end, allocation, config):
    fee, slip = config.fee_bps / 10000, config.execution_bps / 10000
    index = pd.date_range(start, end, freq="15min", inclusive="left")
    cash = config.initial_equity * (1 - allocation)
    closes = np.full(len(index), cash)
    lows = np.full(len(index), cash)
    for frame in candles.values():
        frame = frame.loc[index]
        budget = config.initial_equity * allocation / len(candles)
        qty = budget / (frame.open.iloc[0] * (1 + slip) * (1 + fee))
        closes += qty * frame.close.to_numpy() * (1 - slip) * (1 - fee)
        lows += qty * frame.low.to_numpy() * (1 - slip) * (1 - fee)
    peak, drawdown = config.initial_equity, 0.
    for low, close in zip(lows, closes):
        drawdown = max(drawdown, 1 - low / peak)
        peak = max(peak, close)
    return {"initial_allocation_percent": allocation * 100,
            "return_percent": (closes[-1] / config.initial_equity - 1) * 100,
            "max_drawdown_percent": drawdown * 100,
            "note": "Equal initial BTC/ETH allocation, no rebalancing or stops. Risk/exposure not matched to strategy; quote-equivalent fees."}
