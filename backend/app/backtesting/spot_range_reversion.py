"""Frozen range hypothesis. Research signals only; no operational registration."""
import numpy as np
import pandas as pd

from app.backtesting.spot_pullback_comparison import aggregate
from app.backtesting.spot_pullback_research import BAR, seeded_average, validate_candles

VERSION = "SPOT_RANGE_REVERSION_HYPOTHESIS_V1"


def wilder(series, n=14):
    valid = series.dropna()
    if not valid.empty and series.loc[valid.index[0]:].isna().any():
        raise ValueError("Internal missing indicator data")
    return seeded_average(valid, n, 1 / n).reindex(series.index)


def range_indicators(frame):
    out = frame.copy()
    previous = frame.close.shift()
    tr = pd.concat([frame.high - frame.low, (frame.high - previous).abs(),
                    (frame.low - previous).abs()], axis=1).max(axis=1)
    tr.iloc[0] = np.nan  # no previous close/high/low
    up, down = frame.high.diff(), -frame.low.diff()
    plus = up.where((up > down) & (up > 0), 0.)
    minus = down.where((down > up) & (down > 0), 0.)
    plus.iloc[0] = minus.iloc[0] = np.nan
    out["tr"] = tr
    out["atr"] = wilder(tr)
    smoothed_plus, smoothed_minus = wilder(plus), wilder(minus)
    di_plus = (100 * smoothed_plus / out.atr).mask(out.atr.eq(0), 0.)
    di_minus = (100 * smoothed_minus / out.atr).mask(out.atr.eq(0), 0.)
    total = di_plus + di_minus
    dx = (100 * (di_plus - di_minus).abs() / total).mask(total.eq(0), 0.)
    out["adx"] = wilder(dx)
    out["ema50"] = seeded_average(frame.close, 50, 2 / 51)
    return out


def build_range_features(frame):
    frame = validate_candles(frame)
    hourly = range_indicators(aggregate(frame, 60))
    context = range_indicators(aggregate(frame, 240))
    context["range_ok"] = (context.adx < 20) & ((context.ema50 - context.ema50.shift(6)).abs() <= context.atr)
    context["ready"] = np.arange(len(context)) >= 249
    context.index += pd.Timedelta(hours=4)
    hourly["mean"] = hourly.close.rolling(20).mean()
    hourly["lower"] = hourly["mean"] - 2 * hourly.close.rolling(20).std(ddof=0)
    hourly["setup"] = ((hourly.close.shift() < hourly.lower.shift()) &
                       (hourly.close > hourly.lower) & (hourly.close > hourly.open) &
                       (hourly.close < hourly["mean"]) & (hourly.tr <= 2 * hourly.atr.shift()))
    hourly["stop"] = hourly.low.rolling(2).min() - .25 * hourly.atr
    hourly["fixed_target"] = hourly["mean"]
    hourly["turnover"] = frame.quote_volume.resample("1D").sum().shift().rolling(30).median().reindex(
        hourly.index.floor("D")).to_numpy()
    hourly.index += pd.Timedelta(hours=1)
    regime = context.reindex(hourly.index, method="ffill")
    hourly["signal"] = hourly.setup & regime.range_ok.eq(True) & regime.ready.eq(True) & (hourly.turnover >= 50_000_000)
    hourly["trend_exit"] = regime.adx >= 25
    hourly["regime_adx"] = regime.adx
    hourly["entry_cap_atr"], hourly["max_stop_atr"], hourly["max_hold_hours"] = .25, 3., 24
    hourly["regime_exit_reason"] = "RANGE_BREAK"
    fine = frame.copy()
    fine.index += BAR
    hourly["quote_volume"] = fine.quote_volume.reindex(hourly.index)
    out = hourly.reindex(fine.index, method="ffill")
    out["signal"] = hourly.signal.reindex(fine.index, fill_value=False)
    out["trend_exit"] = out.trend_exit.eq(True)
    return out
