"""Frozen-entry, read-only exit sensitivity study; never an execution signal.

Uses final 5m futures OHLC, NOT archived one-second mark ticks. All alternatives
must have the same complete path through the recorded maximum holding horizon.
Funding is matched to stored venue events for each alternative holding path.
"""
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.paper_trading.exit_policy import STAGED_EXIT_POLICIES
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit

POLICIES = ("IMMEDIATE", "DELAYED_1R", "PROFIT_PROTECTION")
STEP = timedelta(minutes=5)
FUNDING_STEP = timedelta(hours=8)
FUNDING_MATCH_TOLERANCE = timedelta(minutes=5)
R_THRESHOLDS = (0.25, 0.5, 1.0)


def _positive(value):
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value) and value > 0


def _naive_utc(value):
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _expected_funding_times(opened_at, closed_at):
    """Return Binance's regular 00:00/08:00/16:00 UTC funding slots."""
    opened_at, closed_at = _naive_utc(opened_at), _naive_utc(closed_at)
    if opened_at is None or closed_at is None or closed_at <= opened_at:
        return []
    epoch = datetime(1970, 1, 1)
    step_seconds = int(FUNDING_STEP.total_seconds())
    next_slot = int((opened_at - epoch).total_seconds() // step_seconds) + 1
    cursor = epoch + timedelta(seconds=next_slot * step_seconds)
    result = []
    while cursor <= closed_at:
        result.append(cursor)
        cursor += FUNDING_STEP
    return result


def _funding_for_path(record, settlements, funding_events):
    """Apply stored funding events to the fraction open at each expected slot."""
    final_exit = max((stamp for stamp, _ in settlements), default=None)
    expected = _expected_funding_times(record.opened_at, final_exit)
    if not expected:
        return dict(status="COMPLETE_NO_EVENT", expected_events=0, matched_events=0,
                    missing_events=[], cost_fraction=0.0)

    candidates = []
    for event in funding_events or ():
        event_time = _naive_utc(getattr(event, "funding_time", None))
        rate = getattr(event, "rate", None)
        if event_time is not None and isinstance(rate, (float, int)) and math.isfinite(rate):
            candidates.append((event_time, float(rate)))
    used, matched, missing = set(), [], []
    for slot in expected:
        options = [
            (abs((event_time - slot).total_seconds()), index, event_time, rate)
            for index, (event_time, rate) in enumerate(candidates)
            if index not in used and abs(event_time - slot) <= FUNDING_MATCH_TOLERANCE
        ]
        if not options:
            missing.append(slot.isoformat())
            continue
        _, index, event_time, rate = min(options)
        used.add(index)
        matched.append((event_time, rate))
    if missing:
        return dict(status="INCOMPLETE", expected_events=len(expected), matched_events=len(matched),
                    missing_events=missing, cost_fraction=None)

    sign = 1 if record.side == "LONG" else -1
    cost = 0.0
    for event_time, rate in matched:
        exited = sum(amount for stamp, amount in settlements if _naive_utc(stamp) < event_time)
        remaining = max(0.0, 1.0 - exited)
        cost += rate * sign * remaining
    return dict(status="COMPLETE", expected_events=len(expected), matched_events=len(matched),
                missing_events=[], cost_fraction=cost)


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


def _percentile(values, percentile):
    """Return a deterministic linearly interpolated percentile."""
    ordered = sorted(float(value) for value in values if value is not None and math.isfinite(value))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(percentile)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _bar_excursions(record, bar):
    """Return favourable/adverse moves for a validated bar in entry-return units."""
    sign = 1 if record.side == "LONG" else -1
    deadline = record.opened_at + timedelta(hours=record.max_hold_hours)
    overlap = bar.open_time < record.opened_at or bar.close_time > deadline
    if overlap:
        high = low = bar.close_price
    else:
        high, low = bar.high_price, bar.low_price
    favourable_price = high if sign == 1 else low
    adverse_price = low if sign == 1 else high
    favourable = max(0.0, sign * (favourable_price / record.entry_price - 1))
    adverse = max(0.0, -sign * (adverse_price / record.entry_price - 1))
    return favourable, adverse


def _full_horizon_excursions(record, path):
    """Measure frozen-entry geometry over the complete recorded holding horizon."""
    risk_fraction = abs(record.entry_price - record.initial_stop_loss) / record.entry_price
    mfe = mae = 0.0
    mfe_at = None
    threshold_minutes = {threshold: None for threshold in R_THRESHOLDS}
    for bar in path:
        favourable, adverse = _bar_excursions(record, bar)
        mae = max(mae, adverse)
        if favourable > mfe:
            mfe = favourable
            mfe_at = bar.close_time
        favourable_r = favourable / risk_fraction
        elapsed = max(0.0, (bar.close_time - record.opened_at).total_seconds() / 60)
        for threshold in R_THRESHOLDS:
            if threshold_minutes[threshold] is None and favourable_r >= threshold:
                threshold_minutes[threshold] = elapsed
    return {
        "mfe_percent": round(mfe * 100, 6),
        "mae_percent": round(mae * 100, 6),
        "mfe_r": round(mfe / risk_fraction, 6),
        "mae_r": round(mae / risk_fraction, 6),
        "mfe_at": mfe_at.isoformat() if mfe_at is not None else None,
        "time_to_mfe_minutes": (
            round(max(0.0, (mfe_at - record.opened_at).total_seconds() / 60), 3)
            if mfe_at is not None else None
        ),
        "time_to_0_25r_minutes": threshold_minutes[0.25],
        "time_to_0_5r_minutes": threshold_minutes[0.5],
        "time_to_1r_minutes": threshold_minutes[1.0],
    }


def _exit_taxonomy(events, entry, side):
    """Classify exits without collapsing every loss into pre-T1 stop."""
    if not events:
        return "NO_EXIT"
    final = events[-1]
    reason = final["reason"]
    target1_hit = any(event["reason"] == "TARGET1" for event in events)
    if reason == "TARGET2":
        return "TARGET2"
    if reason == "STOP_AFTER_T1":
        return "TARGET1_THEN_STOP"
    if reason == "TIME_EXIT":
        return "TARGET1_THEN_TIME_EXIT" if target1_hit else "PRE_T1_TIME_EXIT"
    if reason != "STOP_BEFORE_T1":
        return reason
    sign = 1 if side == "LONG" else -1
    trigger_return = sign * (float(final["trigger"]) / float(entry) - 1)
    if trigger_return > 1e-9:
        return "PRE_T1_PROTECTED_PROFIT_STOP"
    if trigger_return >= -1e-9:
        return "PRE_T1_BREAKEVEN_STOP"
    return "INITIAL_OR_ADVERSE_STOP"


def _summarize_exit_quality(values):
    """Summarize entry/exit geometry without using the old 1-win-rate shortcut."""
    if not values:
        return {}
    taxonomies = Counter(value["exit_taxonomy"] for value in values)
    economics = Counter(value["economic_result"] for value in values)
    winners = [value for value in values if value["economic_result"] == "WIN"]
    losers = [value for value in values if value["economic_result"] == "LOSS"]
    pre_t1_stops = [
        value for value in values
        if value["exit_taxonomy"] in {
            "INITIAL_OR_ADVERSE_STOP",
            "PRE_T1_BREAKEVEN_STOP",
            "PRE_T1_PROTECTED_PROFIT_STOP",
        }
    ]

    def percentile(items, field, level):
        value = _percentile((item.get(field) for item in items), level)
        return round(value, 6) if value is not None else None

    def percentage(numerator, denominator):
        return round(100 * numerator / denominator, 6) if denominator else None

    recovered = sum(value["recovered_t1_after_pre_t1_stop"] for value in pre_t1_stops)
    return {
        "exit_taxonomy_counts": dict(sorted(taxonomies.items())),
        "economic_result_counts": dict(sorted(economics.items())),
        "winner_mae_r_p50": percentile(winners, "held_bar_mae_r", 0.50),
        "winner_mae_r_p75": percentile(winners, "held_bar_mae_r", 0.75),
        "loser_mfe_r_p50": percentile(losers, "held_bar_mfe_r", 0.50),
        "loser_mfe_r_p75": percentile(losers, "held_bar_mfe_r", 0.75),
        "losers_reaching_0_5r_percent": percentage(
            sum(value["held_bar_mfe_r"] >= 0.5 for value in losers), len(losers)
        ),
        "losers_reaching_1r_percent": percentage(
            sum(value["held_bar_mfe_r"] >= 1.0 for value in losers), len(losers)
        ),
        "time_to_held_mfe_minutes_p50": percentile(values, "time_to_held_mfe_minutes", 0.50),
        "time_to_held_mfe_minutes_p75": percentile(values, "time_to_held_mfe_minutes", 0.75),
        "giveback_percentage_points_p50": percentile(values, "bar_giveback_percentage_points", 0.50),
        "giveback_percentage_points_p75": percentile(values, "bar_giveback_percentage_points", 0.75),
        "pre_t1_stop_count": len(pre_t1_stops),
        "pre_t1_stops_recovering_to_t1_within_horizon": recovered,
        "pre_t1_stop_recovery_rate_percent": percentage(recovered, len(pre_t1_stops)),
        "stop_to_t1_recovery_minutes_p50": percentile(
            [value for value in pre_t1_stops if value["recovered_t1_after_pre_t1_stop"]],
            "minutes_from_stop_to_t1_recovery",
            0.50,
        ),
    }


def replay_trade(record, bars, *, exit_slippage_bps=10.0,
                 protection_activation_percent=1.0, locked_profit_fraction=.5,
                 funding_reserve_bps=5.0, funding_events=None):
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
    planned_entry = getattr(record, "planned_entry_price", None)
    planned_entry = float(planned_entry) if _positive(planned_entry) else None
    if not (initial < entry < t1 < t2 if record.side == "LONG" else t2 < t1 < entry < initial):
        raise ValueError("invalid_geometry")
    fraction = getattr(record, "target1_fraction", None)
    fee_bps = getattr(record, "fee_bps", None)
    if fraction is None or not 0 < fraction < 1 or fee_bps is None or not math.isfinite(fee_bps) or not 0 <= fee_bps <= 100:
        raise ValueError("missing_recorded_fraction_or_fees")
    path = _path(record, bars)
    full_horizon_excursions = _full_horizon_excursions(record, path)
    deadline = record.opened_at + timedelta(hours=record.max_hold_hours)
    sign = 1 if record.side == "LONG" else -1
    risk_fraction = abs(entry - initial) / entry
    slip, fee = exit_slippage_bps / 10000, fee_bps / 10000
    outcomes = {}
    for policy in POLICIES:
        trade = SimpleNamespace(id=record.id, symbol=record.symbol, side=record.side,
            entry_price=entry, initial_stop_loss=initial, stop_loss=initial,
            target1=t1, target2=t2, target1_fraction=fraction, target1_hit_at=None,
            opened_at=record.opened_at, max_hold_hours=None, exit_policy=record.exit_policy,
            trailing_activation_r=1.0 if policy == "DELAYED_1R" else 0.0)
        remaining, pnl, best, ambiguous = 1.0, 0.0, 0.0, 0
        held_mfe = held_mae = 0.0
        held_mfe_at = None
        post_fill_gross = exit_slippage_cost = fee_cost = 0.0
        signal_gross = entry_slippage_cost = 0.0 if planned_entry is not None else None
        events = []
        settlements = []

        def settle(trigger, amount, reason, stamp):
            nonlocal remaining, pnl, post_fill_gross, exit_slippage_cost, fee_cost
            nonlocal signal_gross, entry_slippage_cost
            fill = trigger * (1 - sign * slip)
            gross_from_fill = sign * (trigger / entry - 1)
            filled_return = sign * (fill / entry - 1)
            leg_exit_slippage = gross_from_fill - filled_return
            leg_fee = fee * (1 + fill / entry)
            net = filled_return - leg_fee
            pnl += record.position_notional_inr * amount * net
            post_fill_gross += amount * gross_from_fill
            exit_slippage_cost += amount * leg_exit_slippage
            fee_cost += amount * leg_fee
            if planned_entry is not None:
                # Express every component on the recorded entry-notional basis
                # so the decomposition is additive even when entry != plan.
                gross_from_signal = sign * (trigger - planned_entry) / entry
                signal_gross += amount * gross_from_signal
                entry_slippage_cost += amount * sign * (entry - planned_entry) / entry
            remaining = max(0.0, remaining - amount)
            settlements.append((stamp, amount))
            events.append(dict(reason=reason, at=stamp.isoformat(), fraction=amount,
                               trigger=trigger, fill=fill))

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
            bar_mfe, bar_mae = _bar_excursions(record, bar)
            held_mae = max(held_mae, bar_mae)
            if bar_mfe > held_mfe:
                held_mfe = bar_mfe
                held_mfe_at = bar.close_time
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
        funding = _funding_for_path(record, settlements, funding_events) if funding_events is not None else dict(
            status="NOT_REQUESTED", expected_events=None, matched_events=None,
            missing_events=[], cost_fraction=None)
        funding_cost = funding["cost_fraction"]
        net_before_funding = pnl / record.position_notional_inr
        net_after_funding = net_before_funding - funding_cost if funding_cost is not None else None
        reconciliation = post_fill_gross - exit_slippage_cost - fee_cost - net_before_funding
        signal_reconciliation = (
            signal_gross - entry_slippage_cost - exit_slippage_cost - fee_cost - net_before_funding
            if signal_gross is not None else None
        )
        decomposition = dict(
            signal_gross_return_percent=round(signal_gross * 100, 6) if signal_gross is not None else None,
            post_fill_gross_return_percent=round(post_fill_gross * 100, 6),
            entry_slippage_cost_percent=round(entry_slippage_cost * 100, 6) if entry_slippage_cost is not None else None,
            exit_slippage_cost_percent=round(exit_slippage_cost * 100, 6),
            fee_cost_percent=round(fee_cost * 100, 6),
            funding_cost_percent=round(funding_cost * 100, 6) if funding_cost is not None else None,
            net_return_before_funding_percent=round(net_before_funding * 100, 6),
            net_return_after_funding_percent=round(net_after_funding * 100, 6) if net_after_funding is not None else None,
            post_fill_reconciliation_error_percent=round(reconciliation * 100, 10),
            signal_reconciliation_error_percent=round(signal_reconciliation * 100, 10) if signal_reconciliation is not None else None,
            planned_entry_available=planned_entry is not None,
            funding_coverage_status=funding["status"],
            funding_events_expected=funding["expected_events"],
            funding_events_matched=funding["matched_events"],
            missing_funding_events=funding["missing_events"],
        )
        taxonomy = _exit_taxonomy(events, entry, record.side)
        terminal_at = _naive_utc(datetime.fromisoformat(events[-1]["at"])) if events else None
        recovered_t1_after_stop = False
        recovery_minutes = None
        if taxonomy in {
            "INITIAL_OR_ADVERSE_STOP",
            "PRE_T1_BREAKEVEN_STOP",
            "PRE_T1_PROTECTED_PROFIT_STOP",
        } and terminal_at is not None:
            for later_bar in path:
                if _naive_utc(later_bar.open_time) < terminal_at:
                    continue
                later_mfe, _ = _bar_excursions(record, later_bar)
                target1_return = sign * (t1 / entry - 1)
                reached = later_mfe >= target1_return
                if reached:
                    recovered_t1_after_stop = True
                    recovery_minutes = max(
                        0.0,
                        (_naive_utc(later_bar.close_time) - terminal_at).total_seconds() / 60,
                    )
                    break
        result_basis = net_after_funding if net_after_funding is not None else net_before_funding
        economic_result = "WIN" if result_basis > 1e-12 else "LOSS" if result_basis < -1e-12 else "BREAKEVEN"
        outcomes[policy] = dict(pnl_before_funding_inr=round(pnl, 4),
            pnl_after_funding_inr=round(record.position_notional_inr * net_after_funding, 4) if net_after_funding is not None else None,
            return_before_funding_percent=round(net_before_funding * 100, 6),
            return_after_funding_percent=round(net_after_funding * 100, 6) if net_after_funding is not None else None,
            target1_hit=trade.target1_hit_at is not None, events=events,
            final_stop=trade.stop_loss, ambiguous_bars=ambiguous,
            observed_close_mfe_percent=round(best * 100, 6),
            held_bar_mfe_percent=round(held_mfe * 100, 6),
            held_bar_mae_percent=round(held_mae * 100, 6),
            held_bar_mfe_r=round(held_mfe / risk_fraction, 6),
            held_bar_mae_r=round(held_mae / risk_fraction, 6),
            time_to_held_mfe_minutes=(
                round(max(0.0, (held_mfe_at - record.opened_at).total_seconds() / 60), 3)
                if held_mfe_at is not None else None
            ),
            exit_taxonomy=taxonomy,
            economic_result=economic_result,
            recovered_t1_after_pre_t1_stop=recovered_t1_after_stop,
            minutes_from_stop_to_t1_recovery=(round(recovery_minutes, 3) if recovery_minutes is not None else None),
            giveback_percentage_points=round(best * 100 - net_before_funding * 100, 6),
            bar_giveback_percentage_points=round(held_mfe * 100 - net_before_funding * 100, 6),
            cost_decomposition=decomposition,
            full_horizon_excursions=full_horizon_excursions)
    return outcomes


def compare_records(records, bars_by_symbol, funding_events_by_symbol=None,
                    slippage_scenarios=None, **assumptions):
    rows, excluded = [], Counter()
    sensitivity = defaultdict(list)
    base_slippage = float(assumptions.get("exit_slippage_bps", 10.0))
    requested_scenarios = tuple(float(value) for value in (slippage_scenarios or ()))
    scenarios = tuple(dict.fromkeys((base_slippage, *requested_scenarios)))
    if any(not math.isfinite(value) or not 0 <= value <= 100 for value in scenarios):
        raise ValueError("invalid_slippage_scenario")
    for record in records:
        try:
            funding_events = (
                funding_events_by_symbol.get(record.symbol, [])
                if funding_events_by_symbol is not None else None
            )
            outcomes = replay_trade(
                record,
                bars_by_symbol.get(record.symbol, []),
                funding_events=funding_events,
                **assumptions,
            )
        except ValueError as error:
            excluded[str(error)] += 1
            continue
        rows.append(dict(trade_id=record.id, symbol=record.symbol, side=record.side,
            strategy_id=record.strategy_id, strategy_version=record.strategy_version,
            opened_at=record.opened_at.isoformat(), entry=record.entry_price,
            planned_entry=getattr(record, "planned_entry_price", None),
            recorded_entry_slippage_percent=getattr(record, "entry_slippage_percent", None),
            notional_inr=record.position_notional_inr, outcomes=outcomes))
        for scenario in scenarios:
            scenario_outcomes = outcomes
            if scenario != base_slippage:
                scenario_assumptions = dict(assumptions)
                scenario_assumptions["exit_slippage_bps"] = scenario
                scenario_outcomes = replay_trade(
                    record,
                    bars_by_symbol.get(record.symbol, []),
                    funding_events=funding_events,
                    **scenario_assumptions,
                )
            for policy, outcome in scenario_outcomes.items():
                sensitivity[(scenario, policy)].append(outcome)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["strategy_id"], row["strategy_version"])].append(row)
    summary = []
    for (strategy, version), group in groups.items():
        for policy in POLICIES:
            values = [r["outcomes"][policy] for r in group]
            returns = [v["return_before_funding_percent"] for v in values]
            decompositions = [v["cost_decomposition"] for v in values]
            after_funding = [
                v["return_after_funding_percent"]
                for v in values if v["return_after_funding_percent"] is not None
            ]

            def average_field(name):
                selected = [value[name] for value in decompositions if value[name] is not None]
                return sum(selected) / len(selected) if selected else None

            wins = sum(v for v in returns if v > 0)
            losses = -sum(v for v in returns if v < 0)
            summary.append(dict(strategy_id=strategy, strategy_version=version, policy=policy,
                paired_trades=len(values), win_rate_percent=100 * sum(v > 0 for v in returns) / len(values),
                average_return_before_funding_percent=sum(returns) / len(values),
                average_return_after_funding_percent=sum(after_funding) / len(after_funding) if after_funding else None,
                mean_pnl_before_funding_inr=sum(v["pnl_before_funding_inr"] for v in values) / len(values),
                equal_notional_profit_factor=wins / losses if losses else None,
                target1_hits=sum(v["target1_hit"] for v in values),
                pre_t1_losing_stops=sum(v["events"][-1]["reason"] == "STOP_BEFORE_T1" and v["pnl_before_funding_inr"] < 0 for v in values),
                planned_entry_coverage=sum(value["planned_entry_available"] for value in decompositions),
                funding_complete_paths=sum(value["funding_coverage_status"] in ("COMPLETE", "COMPLETE_NO_EVENT") for value in decompositions),
                average_signal_gross_return_percent=average_field("signal_gross_return_percent"),
                average_post_fill_gross_return_percent=average_field("post_fill_gross_return_percent"),
                average_entry_slippage_cost_percent=average_field("entry_slippage_cost_percent"),
                average_exit_slippage_cost_percent=average_field("exit_slippage_cost_percent"),
                average_fee_cost_percent=average_field("fee_cost_percent"),
                average_funding_cost_percent=average_field("funding_cost_percent"),
                exit_quality=_summarize_exit_quality(values)))
    fee_distribution = Counter()
    for record in records:
        fee = getattr(record, "fee_bps", None)
        if isinstance(fee, (float, int)) and math.isfinite(fee):
            fee_distribution[f"{float(fee):g}"] += 1
    funding_requested = funding_events_by_symbol is not None
    funding_complete = sum(
        outcome["cost_decomposition"]["funding_coverage_status"] in ("COMPLETE", "COMPLETE_NO_EVENT")
        for row in rows for outcome in row["outcomes"].values()
    )
    funding_paths = len(rows) * len(POLICIES)
    all_decompositions = [
        outcome["cost_decomposition"]
        for row in rows for outcome in row["outcomes"].values()
    ]
    sensitivity_summary = []
    for (scenario, policy), values in sorted(sensitivity.items()):
        decompositions = [value["cost_decomposition"] for value in values]
        complete_after_funding = [
            value["return_after_funding_percent"]
            for value in values if value["return_after_funding_percent"] is not None
        ]
        sensitivity_summary.append(dict(
            exit_slippage_bps=scenario,
            policy=policy,
            paired_trades=len(values),
            average_post_fill_gross_return_percent=sum(
                value["post_fill_gross_return_percent"] for value in decompositions
            ) / len(values),
            average_exit_slippage_cost_percent=sum(
                value["exit_slippage_cost_percent"] for value in decompositions
            ) / len(values),
            average_fee_cost_percent=sum(
                value["fee_cost_percent"] for value in decompositions
            ) / len(values),
            average_net_return_before_funding_percent=sum(
                value["return_before_funding_percent"] for value in values
            ) / len(values),
            average_net_return_after_funding_percent=(
                sum(complete_after_funding) / len(complete_after_funding)
                if complete_after_funding else None
            ),
            funding_complete_paths=len(complete_after_funding),
        ))
    overall_summary = []
    for policy in POLICIES:
        values = sensitivity.get((base_slippage, policy), [])
        if not values:
            continue
        decompositions = [value["cost_decomposition"] for value in values]
        before = [value["return_before_funding_percent"] for value in values]
        after = [
            value["return_after_funding_percent"]
            for value in values if value["return_after_funding_percent"] is not None
        ]

        def mean_available(name):
            selected = [value[name] for value in decompositions if value[name] is not None]
            return sum(selected) / len(selected) if selected else None

        wins = sum(value for value in before if value > 0)
        losses = -sum(value for value in before if value < 0)
        after_wins = sum(value for value in after if value > 0)
        after_losses = -sum(value for value in after if value < 0)
        overall_summary.append(dict(
            policy=policy,
            paired_trades=len(values),
            win_rate_before_funding_percent=100 * sum(value > 0 for value in before) / len(before),
            average_return_before_funding_percent=sum(before) / len(before),
            total_pnl_before_funding_inr=sum(value["pnl_before_funding_inr"] for value in values),
            profit_factor_before_funding=wins / losses if losses else None,
            funding_complete_paths=len(after),
            win_rate_after_funding_percent=100 * sum(value > 0 for value in after) / len(after) if after else None,
            average_return_after_funding_percent=sum(after) / len(after) if after else None,
            profit_factor_after_funding=after_wins / after_losses if after_losses else None,
            target1_hits=sum(value["target1_hit"] for value in values),
            pre_t1_losing_stops=sum(
                value["events"][-1]["reason"] == "STOP_BEFORE_T1"
                and value["pnl_before_funding_inr"] < 0 for value in values
            ),
            average_signal_gross_return_percent=mean_available("signal_gross_return_percent"),
            average_post_fill_gross_return_percent=mean_available("post_fill_gross_return_percent"),
            average_entry_slippage_cost_percent=mean_available("entry_slippage_cost_percent"),
            average_exit_slippage_cost_percent=mean_available("exit_slippage_cost_percent"),
            average_fee_cost_percent=mean_available("fee_cost_percent"),
            average_funding_cost_percent=mean_available("funding_cost_percent"),
            exit_quality=_summarize_exit_quality(values),
        ))
    return dict(engine="matched_exit_sensitivity_v2b", status=(
            "INSUFFICIENT_DATA" if not rows else
            "RESEARCH_ONLY_AFTER_STORED_FUNDING" if funding_requested and funding_complete == funding_paths else
            "RESEARCH_ONLY_PARTIAL_FUNDING_COVERAGE" if funding_requested else
            "APPROXIMATE_BEFORE_FUNDING"),
        promotion_allowed=False, input_trades=len(records), paired_trades=len(rows), exclusions=dict(excluded),
        assumptions={"exit_slippage_bps": 10, "protection_activation_percent": 1,
                     "locked_profit_fraction": .5, "funding_reserve_bps": 5, **assumptions},
        cost_coverage={"fee_bps_distribution_selected_inputs": dict(sorted(fee_distribution.items())),
                       "planned_entry_trades": sum(_positive(getattr(record, "planned_entry_price", None)) for record in records),
                       "entry_slippage_snapshot_trades": sum(
                           getattr(record, "entry_slippage_percent", None) is not None for record in records
                       ),
                       "funding_requested": funding_requested,
                       "stored_funding_events_loaded": sum(
                           len(events) for events in (funding_events_by_symbol or {}).values()
                       ),
                       "funding_complete_policy_paths": funding_complete,
                       "funding_policy_paths": funding_paths,
                       "maximum_absolute_reconciliation_error_percent": max(
                           (abs(value["post_fill_reconciliation_error_percent"]) for value in all_decompositions),
                           default=0.0,
                       )},
        overall_summary=overall_summary,
        slippage_sensitivity=sensitivity_summary,
        limitations=["5m futures trade candles are not one-second mark ticks.",
            "Stop-first collisions; entry/deadline overlapping bars use close only; updates effective next bar.",
            "Original exit does not truncate the alternative path. Full holding horizon required.",
            "Only complete stored 00:00/08:00/16:00 UTC Binance funding paths receive after-funding results; missing events are unknown, not zero.",
            "Exceptional venue funding-interval changes are not reconstructed in V2B.",
            "Entry and exit fills are simulated paper evidence, not actual exchange executions.",
            "Intrabar MFE/MAE use complete 5m candle ranges; ordering inside a candle is unknown and values on an exit candle are bounds, not tick-exact paths.",
            "Post-stop T1 recovery is hypothetical full-horizon evidence and does not imply that a wider stop would have been profitable.",
            "Conditioned on recorded entries; overlapping alternatives do not form an executable portfolio. Account drawdown is not estimated.",
            "No automatic winner, parameter update, paper order, or live approval."], summary=summary, trades=rows)
