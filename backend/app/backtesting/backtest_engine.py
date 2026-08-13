from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone

from app.backtesting.performance_engine import calculate_performance
from app.trading.futures_cost_model import DEFAULT_FEE_BPS


ENGINE_VERSION = "backtester_v2"


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    position_size_percent: float = 100.0
    stop_percent: float = 1.0
    target_percent: float = 2.0
    fee_bps: float = DEFAULT_FEE_BPS
    slippage_bps: float = 2.0

    def __post_init__(self):
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be greater than zero")
        if not 0 < self.position_size_percent <= 100:
            raise ValueError("position_size_percent must be between 0 and 100")
        if self.stop_percent <= 0 or self.target_percent <= 0:
            raise ValueError("stop_percent and target_percent must be greater than zero")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("fee_bps and slippage_bps cannot be negative")


def chronological_candles(candles):
    return _chronological_candles(candles)


def run_backtest(
    candles,
    signal,
    stop_percent=1,
    target_percent=2,
    *,
    initial_capital=10_000,
    position_size_percent=100,
    fee_bps=DEFAULT_FEE_BPS,
    slippage_bps=2,
):
    """Run a chronological, single-position directional baseline.

    A direction observed after candle N can only enter at candle N+1's open.
    The entry candle may then trigger an exit because its high/low occurs after
    that open. If stop and target are both touched, the stop wins so an unknown
    intrabar path is never resolved in the strategy's favor.
    """

    side = str(signal or "").upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("signal must be LONG or SHORT")

    config = BacktestConfig(
        initial_capital=float(initial_capital),
        position_size_percent=float(position_size_percent),
        stop_percent=float(stop_percent),
        target_percent=float(target_percent),
        fee_bps=float(fee_bps),
        slippage_bps=float(slippage_bps),
    )
    ordered_candles = _chronological_candles(candles)
    capital = config.initial_capital
    trades = []
    equity_curve = [
        {
            "label": _time_label(ordered_candles[0]) if ordered_candles else "START",
            "equity": round(capital, 2),
        }
    ]
    entry_index = 1
    exposed_candles = 0

    while entry_index < len(ordered_candles) and capital > 0:
        entry_candle = ordered_candles[entry_index]
        raw_entry = _price(entry_candle, "open_price", "close_price")
        if raw_entry is None:
            entry_index += 1
            continue

        entry_fill = _adverse_fill(raw_entry, side, config.slippage_bps, entering=True)
        stop, target = _levels(entry_fill, side, config)
        allocated_capital = capital * (config.position_size_percent / 100)
        quantity = allocated_capital / entry_fill
        exit_details = None

        for exit_index in range(entry_index, len(ordered_candles)):
            candle = ordered_candles[exit_index]
            trigger = _exit_trigger(candle, side, stop, target)
            if trigger is not None:
                trigger_type, trigger_price = trigger
                exit_fill = _adverse_fill(
                    trigger_price,
                    side,
                    config.slippage_bps,
                    entering=False,
                )
                exit_details = (exit_index, candle, trigger_type, trigger_price, exit_fill)
                break

        if exit_details is None:
            exit_index = len(ordered_candles) - 1
            exit_candle = ordered_candles[exit_index]
            raw_exit = _price(exit_candle, "close_price", "open_price")
            if raw_exit is None:
                break
            exit_details = (
                exit_index,
                exit_candle,
                "END_OF_DATA",
                raw_exit,
                _adverse_fill(raw_exit, side, config.slippage_bps, entering=False),
            )

        exit_index, exit_candle, exit_reason, trigger_price, exit_fill = exit_details
        entry_fee = entry_fill * quantity * _bps_rate(config.fee_bps)
        exit_fee = exit_fill * quantity * _bps_rate(config.fee_bps)
        gross_pnl = (
            (exit_fill - entry_fill) * quantity
            if side == "LONG"
            else (entry_fill - exit_fill) * quantity
        )
        fees = entry_fee + exit_fee
        net_pnl = gross_pnl - fees
        pnl_percent = (net_pnl / allocated_capital) * 100 if allocated_capital else 0
        capital += net_pnl
        result = "WIN" if net_pnl > 0 else "LOSS" if net_pnl < 0 else "BREAKEVEN"
        exposed_candles += exit_index - entry_index + 1

        trades.append(
            {
                "side": side,
                "entry": round(entry_fill, 8),
                "entry_reference": round(raw_entry, 8),
                "entry_time": _time_value(entry_candle),
                "exit": round(exit_fill, 8),
                "exit_reference": round(trigger_price, 8),
                "exit_time": _time_value(exit_candle),
                "stop": round(stop, 8),
                "target": round(target, 8),
                "result": result,
                "exit_reason": exit_reason,
                "gross_pnl": round(gross_pnl, 2),
                "fees": round(fees, 2),
                "pnl": round(net_pnl, 2),
                "pnl_percent": round(pnl_percent, 4),
                "capital_after": round(capital, 2),
                "duration_candles": exit_index - entry_index + 1,
            }
        )
        equity_curve.append(
            {
                "label": _time_label(exit_candle),
                "equity": round(capital, 2),
            }
        )

        if exit_reason == "END_OF_DATA":
            break
        entry_index = exit_index + 1

    performance = calculate_performance(
        trades,
        initial_capital=config.initial_capital,
        final_capital=capital,
        equity_curve=equity_curve,
    )
    candle_span = max(0, len(ordered_candles) - 1)

    return {
        "engine_version": ENGINE_VERSION,
        "strategy": "DIRECTIONAL_REENTRY_BASELINE",
        "signal": side,
        "candle_count": len(ordered_candles),
        "total_trades": len(trades),
        "trades": trades,
        "equity_curve": equity_curve,
        "exposure_percent": round(
            (exposed_candles / candle_span) * 100 if candle_span else 0,
            2,
        ),
        "assumptions": {
            **asdict(config),
            "entry_timing": "NEXT_CANDLE_OPEN",
            "intrabar_collision": "STOP_FIRST",
            "position_policy": "ONE_AT_A_TIME",
            "final_position": "CLOSE_AT_LAST_CANDLE",
            "sharpe_method": "TRADE_RETURN_SQRT_N",
        },
        **performance,
    }


def _chronological_candles(candles):
    indexed = []
    seen = set()
    for index, candle in enumerate(candles or []):
        prices = {
            _price(candle, "open_price", "close_price"),
            _price(candle, "high_price"),
            _price(candle, "low_price"),
            _price(candle, "close_price", "open_price"),
        }
        if None in prices or min(prices) <= 0:
            continue
        timestamp = _sortable_time(candle, index)
        dedupe_key = timestamp if _get_value(candle, "candle_time") is not None else index
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        indexed.append((timestamp, index, candle))
    return [item[2] for item in sorted(indexed, key=lambda item: (item[0], item[1]))]


def _exit_trigger(candle, side, stop, target):
    open_price = _price(candle, "open_price", "close_price")
    high = _price(candle, "high_price", "open_price", "close_price")
    low = _price(candle, "low_price", "open_price", "close_price")
    if side == "LONG":
        if open_price <= stop:
            return "STOP", open_price
        if low <= stop:
            return "STOP", stop
        if high >= target:
            return "TARGET", target
    else:
        if open_price >= stop:
            return "STOP", open_price
        if high >= stop:
            return "STOP", stop
        if low <= target:
            return "TARGET", target
    return None


def _levels(entry, side, config):
    stop_rate = config.stop_percent / 100
    target_rate = config.target_percent / 100
    if side == "LONG":
        return entry * (1 - stop_rate), entry * (1 + target_rate)
    return entry * (1 + stop_rate), entry * (1 - target_rate)


def _adverse_fill(price, side, slippage_bps, *, entering):
    rate = _bps_rate(slippage_bps)
    if entering:
        multiplier = 1 + rate if side == "LONG" else 1 - rate
    else:
        multiplier = 1 - rate if side == "LONG" else 1 + rate
    return float(price) * multiplier


def _bps_rate(value):
    return float(value) / 10_000


def _price(candle, *names):
    for name in names:
        value = _get_value(candle, name)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _get_value(candle, name):
    if isinstance(candle, dict):
        return candle.get(name)
    return getattr(candle, name, None)


def _sortable_time(candle, fallback_index):
    value = _get_value(candle, "candle_time")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if value is not None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (TypeError, ValueError):
            pass
    return float(fallback_index)


def _time_value(candle):
    value = _get_value(candle, "candle_time")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _time_label(candle):
    return _time_value(candle) or "UNKNOWN"
