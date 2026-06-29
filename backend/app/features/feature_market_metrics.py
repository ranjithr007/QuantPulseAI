from __future__ import annotations

import math
import statistics
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Volatility reference values are expressed as percentages. A component reaches
# its maximum points when the measured value is equal to or above its reference.
# These are starting values for crypto markets and should later be calibrated
# using QuantPulse AI backtest results.
TIMEFRAME_CONFIG: dict[str, dict[str, float | int]] = {
    "1m": {
        "atr_ref_pct": 0.35,
        "bb_ref_pct": 1.50,
        "return_std_ref_pct": 0.25,
        "range_ref_pct": 0.45,
        "liquidity_recent_bars": 10,
        "liquidity_baseline_bars": 50,
    },
    "3m": {
        "atr_ref_pct": 0.50,
        "bb_ref_pct": 2.00,
        "return_std_ref_pct": 0.35,
        "range_ref_pct": 0.65,
        "liquidity_recent_bars": 8,
        "liquidity_baseline_bars": 40,
    },
    "5m": {
        "atr_ref_pct": 0.70,
        "bb_ref_pct": 2.75,
        "return_std_ref_pct": 0.50,
        "range_ref_pct": 0.90,
        "liquidity_recent_bars": 6,
        "liquidity_baseline_bars": 36,
    },
    "15m": {
        "atr_ref_pct": 1.10,
        "bb_ref_pct": 4.00,
        "return_std_ref_pct": 0.80,
        "range_ref_pct": 1.40,
        "liquidity_recent_bars": 5,
        "liquidity_baseline_bars": 30,
    },
    "30m": {
        "atr_ref_pct": 1.50,
        "bb_ref_pct": 5.50,
        "return_std_ref_pct": 1.10,
        "range_ref_pct": 1.90,
        "liquidity_recent_bars": 5,
        "liquidity_baseline_bars": 30,
    },
    "1h": {
        "atr_ref_pct": 2.00,
        "bb_ref_pct": 7.00,
        "return_std_ref_pct": 1.50,
        "range_ref_pct": 2.60,
        "liquidity_recent_bars": 4,
        "liquidity_baseline_bars": 24,
    },
    "2h": {
        "atr_ref_pct": 2.75,
        "bb_ref_pct": 9.00,
        "return_std_ref_pct": 2.00,
        "range_ref_pct": 3.40,
        "liquidity_recent_bars": 4,
        "liquidity_baseline_bars": 24,
    },
    "4h": {
        "atr_ref_pct": 3.75,
        "bb_ref_pct": 12.00,
        "return_std_ref_pct": 2.75,
        "range_ref_pct": 4.50,
        "liquidity_recent_bars": 3,
        "liquidity_baseline_bars": 21,
    },
    "6h": {
        "atr_ref_pct": 4.50,
        "bb_ref_pct": 14.00,
        "return_std_ref_pct": 3.25,
        "range_ref_pct": 5.25,
        "liquidity_recent_bars": 3,
        "liquidity_baseline_bars": 20,
    },
    "8h": {
        "atr_ref_pct": 5.25,
        "bb_ref_pct": 16.00,
        "return_std_ref_pct": 3.75,
        "range_ref_pct": 6.00,
        "liquidity_recent_bars": 3,
        "liquidity_baseline_bars": 20,
    },
    "12h": {
        "atr_ref_pct": 6.25,
        "bb_ref_pct": 19.00,
        "return_std_ref_pct": 4.50,
        "range_ref_pct": 7.00,
        "liquidity_recent_bars": 3,
        "liquidity_baseline_bars": 20,
    },
    "1d": {
        "atr_ref_pct": 8.00,
        "bb_ref_pct": 25.00,
        "return_std_ref_pct": 5.50,
        "range_ref_pct": 9.00,
        "liquidity_recent_bars": 3,
        "liquidity_baseline_bars": 20,
    },
}

TIMEFRAME_ALIASES = {
    "60m": "1h",
    "120m": "2h",
    "240m": "4h",
    "360m": "6h",
    "480m": "8h",
    "720m": "12h",
    "24h": "1d",
    "1day": "1d",
    "day": "1d",
}

DEFAULT_TIMEFRAME = "5m"
MAX_CANDLES = 300
ATR_PERIOD = 14
BB_PERIOD = 20
RETURN_PERIOD = 14
RANGE_PERIOD = 14
MIN_BASELINE_BARS = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _safe_div(
    numerator: float,
    denominator: float,
    fallback: float = 0.0,
) -> float:
    """Return fallback when the denominator is zero or invalid."""
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return fallback
    return numerator / denominator if denominator != 0 else fallback


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else fallback
    except (TypeError, ValueError):
        return fallback


def _normalise_timeframe(timeframe: Optional[str]) -> str:
    value = (timeframe or DEFAULT_TIMEFRAME).strip().lower()
    value = TIMEFRAME_ALIASES.get(value, value)
    return value if value in TIMEFRAME_CONFIG else DEFAULT_TIMEFRAME


def _config_for(timeframe: Optional[str]) -> tuple[str, dict[str, float | int]]:
    normalised = _normalise_timeframe(timeframe)
    return normalised, TIMEFRAME_CONFIG[normalised]


def _empty_volatility_result(
    symbol: Optional[str],
    timeframe: str,
    reason: str,
) -> dict:
    return {
        "symbol": symbol.upper() if symbol else None,
        "timeframe": timeframe,
        "volatility_score": 50.0,
        "volatility": "UNKNOWN",
        "atr": None,
        "atr_pct": None,
        "bb_width": None,
        "log_return_std": None,
        "avg_hl_range_pct": None,
        "source": "CANDLE_DATA",
        "data_confidence": 0.0,
        "is_usable": False,
        "reason": reason,
        "signal_breakdown": {},
    }


def _empty_liquidity_result(
    symbol: Optional[str],
    timeframe: str,
    reason: str,
) -> dict:
    return {
        "symbol": symbol.upper() if symbol else None,
        "timeframe": timeframe,
        "liquidity_score": 50.0,
        "liquidity": "UNKNOWN",
        "volume_trend_ratio": None,
        "turnover_trend_ratio": None,
        "volume_consistency": None,
        "price_impact_proxy": None,
        "price_impact_ratio": None,
        "market_continuity": None,
        "recent_quote_turnover": None,
        "baseline_quote_turnover": None,
        "spread_pct": None,
        "source": "CANDLE_PROXY",
        "data_confidence": 0.0,
        "is_usable": False,
        "reason": reason,
        "signal_breakdown": {},
    }


def _prepare_candles(candles) -> list:
    """
    Keep candles with valid positive OHLC values.

    Candles are expected in oldest-to-newest order. Zero volume is preserved
    because it is useful for the liquidity continuity calculation.
    """
    if not candles:
        return []

    valid = []
    for candle in candles[-MAX_CANDLES:]:
        open_price = _safe_float(getattr(candle, "open_price", None))
        high_price = _safe_float(getattr(candle, "high_price", None))
        low_price = _safe_float(getattr(candle, "low_price", None))
        close_price = _safe_float(getattr(candle, "close_price", None))

        if min(open_price, high_price, low_price, close_price) <= 0:
            continue
        if high_price < low_price:
            continue

        valid.append(candle)

    return valid


def _get_quote_turnover(candle) -> float:
    """
    Return quote-currency turnover for a candle.

    Binance commonly exposes base volume in `volume`. When a quote-volume field
    is available, it is preferred. Otherwise volume * close is used.
    """
    for field_name in (
        "quote_volume",
        "quote_asset_volume",
        "quote_volume_usdt",
        "quoteVolume",
    ):
        value = _safe_float(getattr(candle, field_name, None), fallback=-1.0)
        if value >= 0:
            return value

    volume = max(_safe_float(getattr(candle, "volume", 0.0)), 0.0)
    close_price = max(_safe_float(getattr(candle, "close_price", 0.0)), 0.0)
    return volume * close_price


def _higher_is_better_component(
    ratio: float,
    max_points: float,
    full_score_ratio: float = 1.5,
) -> float:
    """
    Convert a current-to-baseline ratio into points.

    ratio 0.0 -> 0 points
    ratio 1.0 -> about 67% of max points
    ratio 1.5+ -> maximum points
    """
    return clamp(_safe_div(ratio, full_score_ratio) * max_points, 0.0, max_points)


def _lower_is_better_component(
    ratio: float,
    max_points: float,
    best_ratio: float = 0.5,
    worst_ratio: float = 2.0,
) -> float:
    """
    Convert a lower-is-better current-to-baseline ratio into points.

    ratio <= 0.5 -> maximum points
    ratio 1.0    -> roughly two-thirds of max points
    ratio >= 2.0 -> zero points
    """
    if ratio <= best_ratio:
        return max_points
    if ratio >= worst_ratio:
        return 0.0

    fraction = (worst_ratio - ratio) / (worst_ratio - best_ratio)
    return clamp(fraction * max_points, 0.0, max_points)


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def calculate_atr(candles, period: int = ATR_PERIOD) -> float:
    """
    Calculate Wilder Average True Range.

    Requires at least period + 1 valid candles.
    """
    candles = _prepare_candles(candles)

    if len(candles) < period + 1:
        raise ValueError(
            f"ATR({period}) needs at least {period + 1} valid candles, "
            f"got {len(candles)}."
        )

    true_ranges: list[float] = []

    for index in range(1, len(candles)):
        high = _safe_float(candles[index].high_price)
        low = _safe_float(candles[index].low_price)
        previous_close = _safe_float(candles[index - 1].close_price)

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )
        true_ranges.append(max(true_range, 0.0))

    atr = sum(true_ranges[:period]) / period

    for true_range in true_ranges[period:]:
        atr = ((atr * (period - 1)) + true_range) / period

    return atr


def calculate_volatility_metrics(
    candles,
    symbol: Optional[str] = None,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> dict:
    """
    Calculate a timeframe-aware volatility score from candle data.

    The score uses percentage-based metrics, so it is naturally comparable
    across symbols such as BTCUSDT, ETHUSDT, XRPUSDT and DOGEUSDT.
    """
    normalised_timeframe, config = _config_for(timeframe)
    candles = _prepare_candles(candles)

    minimum_candles = max(ATR_PERIOD + 1, BB_PERIOD, RETURN_PERIOD + 1, RANGE_PERIOD)

    if len(candles) < minimum_candles:
        return _empty_volatility_result(
            symbol=symbol,
            timeframe=normalised_timeframe,
            reason=(
                f"insufficient_candles: need {minimum_candles}, "
                f"got {len(candles)}"
            ),
        )

    closes = [_safe_float(c.close_price) for c in candles]
    highs = [_safe_float(c.high_price) for c in candles]
    lows = [_safe_float(c.low_price) for c in candles]
    current_price = closes[-1]

    if current_price <= 0:
        return _empty_volatility_result(
            symbol=symbol,
            timeframe=normalised_timeframe,
            reason="invalid_current_price",
        )

    # 1. ATR percentage - maximum contribution 40 points.
    atr = calculate_atr(candles, period=ATR_PERIOD)
    atr_pct = _safe_div(atr, current_price) * 100.0
    atr_component = clamp(
        _safe_div(atr_pct, float(config["atr_ref_pct"])) * 40.0,
        0.0,
        40.0,
    )

    # 2. Bollinger Band width - maximum contribution 25 points.
    bb_closes = closes[-BB_PERIOD:]
    bb_middle = statistics.mean(bb_closes)
    bb_std = statistics.pstdev(bb_closes)
    bb_width = _safe_div(4.0 * bb_std, bb_middle) * 100.0
    bb_component = clamp(
        _safe_div(bb_width, float(config["bb_ref_pct"])) * 25.0,
        0.0,
        25.0,
    )

    # 3. Standard deviation of recent log returns - maximum 20 points.
    log_returns: list[float] = []
    start_index = max(1, len(closes) - RETURN_PERIOD)

    for index in range(start_index, len(closes)):
        previous_close = closes[index - 1]
        current_close = closes[index]

        if previous_close > 0 and current_close > 0:
            log_returns.append(math.log(current_close / previous_close))

    log_return_std = (
        statistics.pstdev(log_returns) * 100.0
        if len(log_returns) > 1
        else 0.0
    )
    return_component = clamp(
        _safe_div(
            log_return_std,
            float(config["return_std_ref_pct"]),
        )
        * 20.0,
        0.0,
        20.0,
    )

    # 4. Average intrabar high-low range - maximum 15 points.
    high_low_ranges: list[float] = []
    for index in range(len(candles) - RANGE_PERIOD, len(candles)):
        close = closes[index]
        range_pct = _safe_div(highs[index] - lows[index], close) * 100.0
        high_low_ranges.append(max(range_pct, 0.0))

    avg_hl_range_pct = statistics.mean(high_low_ranges) if high_low_ranges else 0.0
    range_component = clamp(
        _safe_div(
            avg_hl_range_pct,
            float(config["range_ref_pct"]),
        )
        * 15.0,
        0.0,
        15.0,
    )

    volatility_score = clamp(
        atr_component + bb_component + return_component + range_component,
        0.0,
        100.0,
    )

    if volatility_score >= 75.0:
        volatility = "EXTREME"
    elif volatility_score >= 60.0:
        volatility = "HIGH"
    elif volatility_score >= 40.0:
        volatility = "MODERATE"
    elif volatility_score >= 20.0:
        volatility = "LOW"
    else:
        volatility = "VERY_LOW"

    # Full confidence at 100 valid candles. Lower sample sizes remain usable.
    data_confidence = clamp((len(candles) / 100.0) * 100.0, 40.0, 100.0)

    return {
        "symbol": symbol.upper() if symbol else None,
        "timeframe": normalised_timeframe,
        "volatility_score": round(volatility_score, 2),
        "volatility": volatility,
        "atr": round(atr, 8),
        "atr_pct": round(atr_pct, 4),
        "bb_width": round(bb_width, 4),
        "log_return_std": round(log_return_std, 6),
        "avg_hl_range_pct": round(avg_hl_range_pct, 4),
        "source": "CANDLE_DATA",
        "data_confidence": round(data_confidence, 2),
        "is_usable": True,
        "reason": None,
        "signal_breakdown": {
            "atr_component": round(atr_component, 2),       # max 40
            "bb_component": round(bb_component, 2),         # max 25
            "return_component": round(return_component, 2), # max 20
            "range_component": round(range_component, 2),   # max 15
        },
    }


# ---------------------------------------------------------------------------
# Liquidity - candle-only proxy
# ---------------------------------------------------------------------------

def calculate_liquidity_metrics(
    candles,
    symbol: Optional[str] = None,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> dict:
    """
    Calculate a symbol-relative candle liquidity proxy from 0 to 100.

    This is not true exchange liquidity because candle data does not contain
    bid-ask spread or order-book depth. It estimates whether the current market
    for the supplied symbol/timeframe is liquid relative to its own recent
    history.

    Components
    ----------
    1. Recent base-volume activity vs historical baseline       : 25 points
    2. Recent quote-turnover activity vs historical baseline    : 20 points
    3. Recent volume consistency                                : 15 points
    4. Relative Amihud-style price impact                       : 30 points
    5. Market continuity / non-zero activity                    : 10 points

    Maximum total: 100 points.
    """
    normalised_timeframe, config = _config_for(timeframe)
    candles = _prepare_candles(candles)

    recent_bars = int(config["liquidity_recent_bars"])
    desired_baseline_bars = int(config["liquidity_baseline_bars"])

    # We need at least one prior close for returns, recent bars, and a meaningful
    # baseline. When fewer than the desired baseline bars are present, the code
    # uses the available baseline but lowers data_confidence.
    minimum_candles = recent_bars + MIN_BASELINE_BARS + 1

    if len(candles) < minimum_candles:
        return _empty_liquidity_result(
            symbol=symbol,
            timeframe=normalised_timeframe,
            reason=(
                f"insufficient_candles: need at least {minimum_candles}, "
                f"got {len(candles)}"
            ),
        )

    closes = [_safe_float(c.close_price) for c in candles]
    volumes = [max(_safe_float(getattr(c, "volume", 0.0)), 0.0) for c in candles]
    quote_turnovers = [max(_get_quote_turnover(c), 0.0) for c in candles]

    if all(volume <= 0 for volume in volumes):
        return _empty_liquidity_result(
            symbol=symbol,
            timeframe=normalised_timeframe,
            reason="no_volume_data",
        )

    available_baseline_bars = len(candles) - recent_bars - 1
    baseline_bars = min(desired_baseline_bars, available_baseline_bars)

    if baseline_bars < MIN_BASELINE_BARS:
        return _empty_liquidity_result(
            symbol=symbol,
            timeframe=normalised_timeframe,
            reason=(
                f"insufficient_baseline: need {MIN_BASELINE_BARS}, "
                f"got {baseline_bars}"
            ),
        )

    recent_start = len(candles) - recent_bars
    baseline_start = recent_start - baseline_bars

    recent_volumes = volumes[recent_start:]
    baseline_volumes = volumes[baseline_start:recent_start]

    recent_turnovers = quote_turnovers[recent_start:]
    baseline_turnovers = quote_turnovers[baseline_start:recent_start]

    # 1. Base-volume activity relative to this symbol's own baseline.
    recent_volume_mean = statistics.mean(recent_volumes)
    positive_baseline_volumes = [value for value in baseline_volumes if value > 0]
    baseline_volume_reference = (
        statistics.median(positive_baseline_volumes)
        if positive_baseline_volumes
        else 0.0
    )
    volume_trend_ratio = _safe_div(
        recent_volume_mean,
        baseline_volume_reference,
        fallback=0.0,
    )
    volume_component = _higher_is_better_component(
        ratio=volume_trend_ratio,
        max_points=25.0,
        full_score_ratio=1.5,
    )

    # 2. Quote turnover relative to this symbol's own baseline.
    recent_quote_turnover = statistics.mean(recent_turnovers)
    positive_baseline_turnovers = [
        value for value in baseline_turnovers if value > 0
    ]
    baseline_quote_turnover = (
        statistics.median(positive_baseline_turnovers)
        if positive_baseline_turnovers
        else 0.0
    )
    turnover_trend_ratio = _safe_div(
        recent_quote_turnover,
        baseline_quote_turnover,
        fallback=0.0,
    )
    turnover_component = _higher_is_better_component(
        ratio=turnover_trend_ratio,
        max_points=20.0,
        full_score_ratio=1.5,
    )

    # 3. Volume consistency. Lower coefficient of variation is better.
    recent_volume_std = (
        statistics.pstdev(recent_volumes)
        if len(recent_volumes) > 1
        else 0.0
    )
    recent_volume_cv = _safe_div(
        recent_volume_std,
        recent_volume_mean,
        fallback=2.0,
    )

    # CV <= 0.30 gets full points. CV >= 2.00 gets zero.
    normalised_cv = clamp((recent_volume_cv - 0.30) / 1.70, 0.0, 1.0)
    consistency_component = (1.0 - normalised_cv) * 15.0
    volume_consistency = 1.0 - normalised_cv

    # 4. Amihud-style price impact: absolute log return / quote turnover.
    # Lower current impact than historical impact means better liquidity.
    price_impacts: list[float] = []

    for index in range(1, len(candles)):
        previous_close = closes[index - 1]
        current_close = closes[index]
        quote_turnover = quote_turnovers[index]

        if previous_close <= 0 or current_close <= 0 or quote_turnover <= 0:
            price_impacts.append(0.0)
            continue

        absolute_return = abs(math.log(current_close / previous_close))
        price_impacts.append(absolute_return / quote_turnover)

    # price_impacts index 0 corresponds to candle index 1, so translate the
    # candle boundaries by one.
    recent_impact_start = max(recent_start - 1, 0)
    baseline_impact_start = max(baseline_start - 1, 0)

    recent_impacts = [
        value for value in price_impacts[recent_impact_start:] if value > 0
    ]
    baseline_impacts = [
        value
        for value in price_impacts[baseline_impact_start:recent_impact_start]
        if value > 0
    ]

    recent_price_impact = (
        statistics.mean(recent_impacts) if recent_impacts else 0.0
    )
    baseline_price_impact = (
        statistics.median(baseline_impacts) if baseline_impacts else 0.0
    )

    if recent_price_impact > 0 and baseline_price_impact > 0:
        price_impact_ratio = recent_price_impact / baseline_price_impact
        price_impact_component = _lower_is_better_component(
            ratio=price_impact_ratio,
            max_points=30.0,
            best_ratio=0.5,
            worst_ratio=2.0,
        )
    else:
        # Missing impact data should not be treated as excellent liquidity.
        price_impact_ratio = None
        price_impact_component = 15.0

    # 5. Market continuity: percentage of recent candles with real activity.
    active_recent_bars = sum(
        1
        for volume, turnover in zip(recent_volumes, recent_turnovers)
        if volume > 0 and turnover > 0
    )
    market_continuity = _safe_div(active_recent_bars, recent_bars, fallback=0.0)
    continuity_component = clamp(market_continuity * 10.0, 0.0, 10.0)

    liquidity_score = clamp(
        volume_component
        + turnover_component
        + consistency_component
        + price_impact_component
        + continuity_component,
        0.0,
        100.0,
    )

    if liquidity_score >= 75.0:
        liquidity = "VERY_HIGH"
    elif liquidity_score >= 60.0:
        liquidity = "HIGH"
    elif liquidity_score >= 40.0:
        liquidity = "MODERATE"
    elif liquidity_score >= 20.0:
        liquidity = "LOW"
    else:
        liquidity = "VERY_LOW"

    baseline_coverage = _safe_div(
        baseline_bars,
        desired_baseline_bars,
        fallback=0.0,
    )

    # Candle-only liquidity can never have the same certainty as spread/depth
    # data, so confidence is capped at 75.
    data_confidence = clamp(
        45.0 + (baseline_coverage * 30.0),
        45.0,
        75.0,
    )

    return {
        "symbol": symbol.upper() if symbol else None,
        "timeframe": normalised_timeframe,
        "liquidity_score": round(liquidity_score, 2),
        "liquidity": liquidity,
        "volume_trend_ratio": round(volume_trend_ratio, 4),
        "turnover_trend_ratio": round(turnover_trend_ratio, 4),
        "volume_consistency": round(volume_consistency, 4),
        "price_impact_proxy": round(recent_price_impact, 12),
        "price_impact_ratio": (
            round(price_impact_ratio, 4)
            if price_impact_ratio is not None
            else None
        ),
        "market_continuity": round(market_continuity, 4),
        "recent_quote_turnover": round(recent_quote_turnover, 2),
        "baseline_quote_turnover": round(baseline_quote_turnover, 2),
        "spread_pct": None,
        "source": "CANDLE_PROXY",
        "data_confidence": round(data_confidence, 2),
        "is_usable": True,
        "reason": None,
        "signal_breakdown": {
            "volume_activity_component": round(volume_component, 2),       # max 25
            "turnover_activity_component": round(turnover_component, 2),   # max 20
            "volume_consistency_component": round(consistency_component, 2), # max 15
            "price_impact_component": round(price_impact_component, 2),     # max 30
            "continuity_component": round(continuity_component, 2),         # max 10
        },
    }


# ---------------------------------------------------------------------------
# Combined convenience method
# ---------------------------------------------------------------------------

def calculate_market_conditions(
    candles,
    symbol: Optional[str] = None,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> dict:
    """Return volatility and candle-liquidity results in one response."""
    return {
        "symbol": symbol.upper() if symbol else None,
        "timeframe": _normalise_timeframe(timeframe),
        "volatility": calculate_volatility(
            candles=candles,
            symbol=symbol,
            timeframe=timeframe,
        ),
        "liquidity": calculate_liquidity(
            candles=candles,
            symbol=symbol,
            timeframe=timeframe,
        ),
    }
