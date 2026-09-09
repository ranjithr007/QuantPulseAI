"""Frozen-entry, read-only exit sensitivity study; never an execution signal.

Uses final 5m futures OHLC, NOT archived one-second mark ticks. All alternatives
must have the same complete path through the recorded maximum holding horizon.
Funding is deliberately unknown rather than copied from an actual shorter trade.
"""
import math
from collections import Counter, defaultdict
from datetime import timedelta
from types import SimpleNamespace

from app.paper_trading.exit_policy import STAGED_EXIT_POLICIES
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit

POLICIES = ("IMMEDIATE", "DELAYED_1R", "PROFIT_PROTECTION")
STEP = timedelta(minutes=5)


def _positive(value):
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value) and value > 0


def _path(trade, bars):
    deadline = trade.opened_at + timedelta(hours=trade.max_hold_hours)
    path = sorted((b for b in bars if b.close_time > trade.opened_at and b.open_time < deadline), key=lambda b: b.open_time)
    if not path or path[0].open_time > trade.opened_at or path[-1].close_time < deadline - timedelta(milliseconds=1):
        raise ValueError("incomplete_holding_horizon")
    for index, bar in enumerate(path):
        prices = (bar.open_price, bar.high_price, bar.low_price, bar.close_price)
        if not all(_positive(p) for p in prices) or not bar.low_price <= min(bar.open_price, bar.close_price) <= max(bar.open_price, bar.close_price) <= bar.high_price:
            raise ValueError("invalid_ohlc")
        if abs((bar.close_time - bar.open_time - STEP).total_seconds()) > .0011:
            raise ValueError("invalid_bar_duration")
        if index and bar.open_time - path[index - 1].open_time != STEP:
            raise ValueError("gap_or_duplicate_candle")
        if bar.symbol != trade.symbol:
            raise ValueError("mixed_symbols")
    return path


def replay_trade(record, bars, *, exit_slippage_bps=10.0,
                 protection_activation_percent=1.0, locked_profit_fraction=.5,
                 funding_reserve_bps=5.0):
    """Same actual entry, initial geometry and INR notional in each alternative.

    Candidate constants are exploratory, not tuned or approved: activate at 1%
    favourable closing move, lock half that move (or a cost-covering floor).
    Stops ratchet only; updates take effect next candle. Entry/deadline-overlap
    candles use close only so pre-entry wicks cannot trigger an exit.
    """
    for value in (exit_slippage_bps, funding_reserve_bps):
        if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("invalid_cost_assumption")
    if not _positive(protection_activation_percent) or not 0 < locked_profit_fraction < 1:
        raise ValueError("invalid_protection_assumption")
    fields = ("entry_price", "initial_stop_loss", "target1", "target2", "position_notional_inr", "max_hold_hours")
    if not all(_positive(getattr(record, key, None)) for key in fields):
        raise ValueError("missing_recorded_geometry_or_notional")
    if record.max_hold_hours > 48 or record.exit_policy not in STAGED_EXIT_POLICIES:
        raise ValueError("unsupported_recorded_policy")
    if record.side not in ("LONG", "SHORT"):
        raise ValueError("invalid_side")
    entry, initial, t1, t2 = (getattr(record, key) for key in fields[:4])
    if not (initial < entry < t1 < t2 if record.side == "LONG" else t2 < t1 < entry < initial):
        raise ValueError("invalid_geometry")
    fraction = getattr(record, "target1_fraction", None)
    fee_bps = getattr(record, "fee_bps", None)
    if fraction is None or not 0 < fraction < 1 or fee_bps is None or not math.isfinite(fee_bps) or not 0 <= fee_bps <= 100:
        raise ValueError("missing_recorded_fraction_or_fees")
    path = _path(record, bars)
    deadline = record.opened_at + timedelta(hours=record.max_hold_hours)
    sign = 1 if record.side == "LONG" else -1
    slip, fee = exit_slippage_bps / 10000, fee_bps / 10000
    outcomes = {}
    for policy in POLICIES:
        trade = SimpleNamespace(id=record.id, symbol=record.symbol, side=record.side,
            entry_price=entry, initial_stop_loss=initial, stop_loss=initial,
            target1=t1, target2=t2, target1_fraction=fraction, target1_hit_at=None,
            opened_at=record.opened_at, max_hold_hours=None, exit_policy=record.exit_policy,
            trailing_activation_r=1.0 if policy == "DELAYED_1R" else 0.0)
        remaining, pnl, best, ambiguous = 1.0, 0.0, 0.0, 0
        events = []

        def settle(trigger, amount, reason, stamp):
            nonlocal remaining, pnl
            fill = trigger * (1 - sign * slip)
            net = sign * (fill / entry - 1) - fee * (1 + fill / entry)
            pnl += record.position_notional_inr * amount * net
            remaining = max(0.0, remaining - amount)
            events.append(dict(reason=reason, at=stamp.isoformat(), fraction=amount, fill=fill))

        def tighten(stop):
            trade.stop_loss = max(trade.stop_loss, stop) if sign == 1 else min(trade.stop_loss, stop)

        for bar in path:
            # OHLC ordering is unknown. Current-stop collisions are stop-first.
            overlap = bar.open_time < record.opened_at or bar.close_time > deadline
            candle = SimpleNamespace(**{k: getattr(bar, k) for k in
                ("open_time", "close_time", "open_price", "high_price", "low_price", "close_price")})
            candle.candle_time = bar.open_time
            if overlap:
                candle.high_price = candle.low_price = candle.open_price = bar.close_price
                ambiguous += 1
            favorable = max(0, sign * (candle.close_price / entry - 1))
            best = max(best, favorable)
            stop_hit = candle.low_price <= trade.stop_loss if sign == 1 else candle.high_price >= trade.stop_loss
            target = t2 if trade.target1_hit_at else t1
            target_hit = candle.high_price >= target if sign == 1 else candle.low_price <= target
            if stop_hit and target_hit:
                ambiguous += 1
            if stop_hit:
                trigger = min(trade.stop_loss, candle.open_price) if sign == 1 else max(trade.stop_loss, candle.open_price)
                settle(trigger, remaining, "STOP_AFTER_T1" if trade.target1_hit_at else "STOP_BEFORE_T1", bar.close_time)
                break
            event = evaluate_paper_trade_exit(trade, candle)
            if event["action"] == "PARTIAL_CLOSE":
                settle(t1, fraction, "TARGET1", bar.close_time)
                trade.target1_hit_at = bar.close_time
                tighten(event["new_stop_loss"])
                if candle.high_price >= t2 if sign == 1 else candle.low_price <= t2:
                    settle(t2, remaining, "TARGET2", bar.close_time)
            elif event["action"] == "CLOSE":
                settle(t2, remaining, "TARGET2", bar.close_time)
            elif event["action"] == "MOVE_STOP":
                tighten(event["new_stop_loss"])
            if remaining <= 1e-9:
                break
            if bar.close_time >= deadline - timedelta(milliseconds=1):
                settle(candle.close_price, remaining, "TIME_EXIT", bar.close_time)
                break
            if policy == "PROFIT_PROTECTION" and favorable * 100 >= protection_activation_percent:
                # Exact fee/slippage break-even threshold, plus an explicit
                # funding reserve. Actual funding remains unmeasured.
                reserve = funding_reserve_bps / 10000
                ratio = ((1 + fee + reserve) / ((1 - fee) * (1 - slip)) if sign == 1
                         else (1 - fee - reserve) / ((1 + fee) * (1 + slip)))
                cost_floor = sign * (ratio - 1)
                protected = max(favorable * locked_profit_fraction, cost_floor)
                if protected < favorable:  # Do not create a stop past current price.
                    tighten(entry * (1 + sign * protected))
        outcomes[policy] = dict(pnl_before_funding_inr=round(pnl, 4),
            return_before_funding_percent=round(pnl / record.position_notional_inr * 100, 6),
            target1_hit=trade.target1_hit_at is not None, events=events,
            final_stop=trade.stop_loss, ambiguous_bars=ambiguous,
            observed_close_mfe_percent=round(best * 100, 6),
            giveback_percentage_points=round(best * 100 - pnl / record.position_notional_inr * 100, 6))
    return outcomes


def compare_records(records, bars_by_symbol, **assumptions):
    rows, excluded = [], Counter()
    for record in records:
        try:
            outcomes = replay_trade(record, bars_by_symbol.get(record.symbol, []), **assumptions)
        except ValueError as error:
            excluded[str(error)] += 1
            continue
        rows.append(dict(trade_id=record.id, symbol=record.symbol, side=record.side,
            strategy_id=record.strategy_id, strategy_version=record.strategy_version,
            opened_at=record.opened_at.isoformat(), entry=record.entry_price,
            notional_inr=record.position_notional_inr, outcomes=outcomes))
    groups = defaultdict(list)
    for row in rows:
        groups[(row["strategy_id"], row["strategy_version"])].append(row)
    summary = []
    for (strategy, version), group in groups.items():
        for policy in POLICIES:
            values = [r["outcomes"][policy] for r in group]
            returns = [v["return_before_funding_percent"] for v in values]
            wins = sum(v for v in returns if v > 0)
            losses = -sum(v for v in returns if v < 0)
            summary.append(dict(strategy_id=strategy, strategy_version=version, policy=policy,
                paired_trades=len(values), win_rate_percent=100 * sum(v > 0 for v in returns) / len(values),
                average_return_before_funding_percent=sum(returns) / len(values),
                mean_pnl_before_funding_inr=sum(v["pnl_before_funding_inr"] for v in values) / len(values),
                equal_notional_profit_factor=wins / losses if losses else None,
                target1_hits=sum(v["target1_hit"] for v in values),
                pre_t1_losing_stops=sum(v["events"][-1]["reason"] == "STOP_BEFORE_T1" and v["pnl_before_funding_inr"] < 0 for v in values)))
    return dict(engine="matched_exit_sensitivity_v1", status="APPROXIMATE_BEFORE_FUNDING" if rows else "INSUFFICIENT_DATA",
        promotion_allowed=False, input_trades=len(records), paired_trades=len(rows), exclusions=dict(excluded),
        assumptions={"exit_slippage_bps": 10, "protection_activation_percent": 1,
                     "locked_profit_fraction": .5, "funding_reserve_bps": 5, **assumptions},
        limitations=["5m futures trade candles are not one-second mark ticks.",
            "Stop-first collisions; entry/deadline overlapping bars use close only; updates effective next bar.",
            "Original exit does not truncate the alternative path. Full holding horizon required.",
            "Funding is unknown, not zero. Results are after fees/slippage but before funding.",
            "Conditioned on recorded entries; overlapping alternatives do not form an executable portfolio. Account drawdown is not estimated.",
            "No automatic winner, parameter update, paper order, or live approval."], summary=summary, trades=rows)
