"""Read-only replay of recorded strategy decisions, not historical rule regeneration.

Each version gets an independent virtual portfolio. Never writes paper trades,
changes strategy parameters, or grants live-execution approval.
"""
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.database.models.market_candles import MarketCandle
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.pipeline_runs import PipelineRun
from app.paper_trading.exit_policy import STAGED_EXIT_POLICIES
from app.paper_trading.fill_model import build_fill_profile, simulate_exit_fill
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.strategies.learning import strategy_definitions
from app.trading.futures_cost_model import DEFAULT_FEE_BPS

ENGINE = "recorded_strategy_comparison_v1"
REPLAY_POLICY_VERSION = "recorded_exit_policy_v2"
CAPITAL = 200000.0
TIMEFRAMES = ("1h", "2h", "4h", "1d")
LIMIT = 60000


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _decision(row, completed_at=None):
    try:
        snapshot = json.loads(row.snapshot_json)
        context = snapshot.get("context") or {}
        plan = snapshot.get("trade_plan") or {}
        available = max(row.effective_timestamp, row.source_timestamp, row.created_at)
        if completed_at is not None:
            available = max(available, completed_at)
        return dict(time=available, timeframe=row.timeframe, decision=row.decision,
                    side=context.get("side"), confidence=_number(row.confidence) or 0,
                    score=abs(_number(context.get("selected_score")) or _number(row.confidence) or 0),
                    plan=plan, id=row.id,
                    trailing_activation_r=context.get("trailing_activation_r"),
                    execution_evidence=context.get("execution_evidence") or {})
    except (ValueError, TypeError, AttributeError):
        return None


def _recorded_trailing_activation(candidate):
    """Use only saved exit metadata; never infer a threshold from today's registry."""
    plan = candidate["plan"]
    sources = (plan, candidate, plan.get("execution_evidence") or {}, candidate.get("execution_evidence") or {})
    if any(not isinstance(source, dict) for source in sources):
        raise ValueError("Recorded exit metadata must be an object")
    values = [source["trailing_activation_r"] for source in sources if source.get("trailing_activation_r") is not None]
    parsed = [_number(value) for value in values]
    if any(isinstance(value, bool) for value in values) or any(value is None or not 0 <= value <= 5 for value in parsed):
        raise ValueError("Recorded trailing activation is invalid")
    if len(set(parsed)) > 1:
        raise ValueError("Recorded trailing activation is inconsistent")
    activation = parsed[0] if parsed else None
    profiles = {source["exit_management_profile"] for source in sources if source.get("exit_management_profile")}
    if len(profiles) > 1:
        raise ValueError("Recorded exit management profiles are inconsistent")
    profile = next(iter(profiles), None)
    if ((profile == "DELAYED_TRAIL_1R_V1" and activation != 1)
            or (profile == "IMMEDIATE_TRAIL_V1" and activation != 0)):
        raise ValueError("Recorded exit profile requires its explicit activation threshold")
    # A genuinely legacy record retains NULL: the monitor's established legacy
    # behavior is immediate trailing, not evidence that zero was recorded.
    return activation, profile


def _open(candidate, bar, equity):
    plan = candidate["plan"]
    levels = [_number(plan.get(key)) for key in ("entry", "stop_loss", "target1", "target2")]
    if any(value is None or value <= 0 for value in levels):
        return None
    entry, stop, t1, t2 = levels
    side = candidate["side"]
    if not (stop < entry < t1 < t2 if side == "LONG" else t2 < t1 < entry < stop):
        return None
    policy = plan.get("exit_policy")
    fraction = _number(plan.get("target1_fraction"))
    hours = _number(plan.get("max_hold_hours"))
    if policy not in STAGED_EXIT_POLICIES or fraction is None or not 0 < fraction < 1 or hours is None or hours <= 0:
        return None  # Do not silently substitute today's policy for missing history.
    try:
        activation, exit_profile = _recorded_trailing_activation(candidate)
    except (ValueError, TypeError):
        return None
    price = float(bar.open_price)
    fill = build_fill_profile(side, price, price * stop / entry, price * t1 / entry,
                              confidence=candidate["confidence"], fee_bps=DEFAULT_FEE_BPS)
    actual = fill["entry_fill_price"]
    return SimpleNamespace(
        id=candidate["id"], symbol=bar.symbol, side=side, entry_price=actual,
        stop_loss=actual * stop / entry, initial_stop_loss=actual * stop / entry,
        target1=actual * t1 / entry, target2=actual * t2 / entry,
        exit_policy=policy, target1_fraction=fraction, max_hold_hours=hours,
        trailing_activation_r=activation, exit_management_profile=exit_profile,
        confidence=candidate["confidence"], risk_reward=abs(t1-entry)/abs(entry-stop),
        opened_at=bar.open_time, target1_hit_at=None, remaining=1.0,
        notional=equity * .85, pnl=0.0, timeframe=candidate["timeframe"],
    )


def replay_version(decisions, bars):
    """5m OHLC replay: stop-first collisions, stop updates effective next bar."""
    decisions = sorted(decisions, key=lambda item: (item["time"], item["id"]))
    latest, cooldown, skipped = {}, {}, Counter()
    index, active, last_close, previous_bar = 0, None, datetime.min, None
    equity, peak, drawdown = CAPITAL, CAPITAL, 0.0
    trades = []
    censored = 0
    fee = DEFAULT_FEE_BPS / 10000

    def settle(price, fraction):
        sign = 1 if active.side == "LONG" else -1
        # INR virtual notional × underlying return; no historical FX conversion.
        active.pnl += active.notional * fraction * (sign * (price / active.entry_price - 1) - fee * (1 + price / active.entry_price))
        active.remaining -= fraction

    for bar in bars:
        if previous_bar is not None and bar.open_time - previous_bar > timedelta(minutes=5):
            if active:
                censored += 1
                active = None
                # A missing exit path invalidates subsequent portfolio accounting.
                break
        previous_bar = bar.open_time
        while index < len(decisions) and decisions[index]["time"] < bar.open_time:
            item = decisions[index]
            latest[item["timeframe"]] = item
            index += 1
        if active is None and equity > 0:
            candidates = [item for item in latest.values()
                          if item["decision"] == "ELIGIBLE" and item["side"] in ("LONG", "SHORT")
                          and last_close < item["time"] < bar.open_time
                          and bar.open_time - item["time"] <= timedelta(minutes=10)]
            for item in sorted(candidates, key=lambda item: (item.get("score", item["confidence"]), item["time"], item["id"]), reverse=True):
                if cooldown.get(item["side"], datetime.min) > bar.open_time:
                    skipped["same_direction_stop_cooldown"] += 1
                    continue
                active = _open(item, bar, equity)
                if active:
                    break
                skipped["unsupported_or_invalid_recorded_plan"] += 1
        if active is None:
            continue
        # A gap through an existing stop fills at the opening price, not the old stop.
        gap = bar.open_price < active.stop_loss if active.side == "LONG" else bar.open_price > active.stop_loss
        if gap:
            fill = simulate_exit_fill(active, bar.open_price, "STOP")
            event = {"action": "CLOSE", "exit_price": fill["exit_fill_price"], "fill_profile": fill}
        elif bar.close_time >= active.opened_at + timedelta(hours=active.max_hold_hours):
            # Preserve stop/target priority at the deadline; force timeout if HOLD/MOVE_STOP.
            event = evaluate_paper_trade_exit(active, bar)
            if event["action"] in ("HOLD", "MOVE_STOP"):
                fill = simulate_exit_fill(active, bar.close_price, "TIME_EXIT")
                event = {"action": "CLOSE", "exit_price": fill["exit_fill_price"], "fill_profile": fill}
        else:
            event = evaluate_paper_trade_exit(active, bar)
        action = event["action"]
        if action == "MOVE_STOP":
            active.stop_loss = max(active.stop_loss, event["new_stop_loss"]) if active.side == "LONG" else min(active.stop_loss, event["new_stop_loss"])
        elif action == "PARTIAL_CLOSE":
            settle(event["exit_price"], active.target1_fraction)
            active.target1_hit_at = bar.close_time
            active.stop_loss = max(active.stop_loss, event["new_stop_loss"]) if active.side == "LONG" else min(active.stop_loss, event["new_stop_loss"])
            # Both targets touched: settle T2, without replaying the same candle's
            # earlier low/high against a stop that did not exist yet.
            t2_hit = bar.high_price >= active.target2 if active.side == "LONG" else bar.low_price <= active.target2
            if t2_hit:
                fill = simulate_exit_fill(active, active.target2, "TARGET2")
                event = {"action": "CLOSE", "exit_price": fill["exit_fill_price"], "fill_profile": fill}
                action = "CLOSE"
            elif bar.close_time >= active.opened_at + timedelta(hours=active.max_hold_hours):
                fill = simulate_exit_fill(active, bar.close_price, "TIME_EXIT")
                event = {"action": "CLOSE", "exit_price": fill["exit_fill_price"], "fill_profile": fill}
                action = "CLOSE"
        if action == "CLOSE":
            settle(event["exit_price"], active.remaining)
            reason = event.get("fill_profile", {}).get("trigger_type", "EXIT")
            equity += active.pnl
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak-equity)/peak*100)
            trades.append(dict(opened_at=active.opened_at.isoformat()+"Z", closed_at=bar.close_time.isoformat()+"Z",
                               side=active.side, timeframe=active.timeframe, entry=active.entry_price,
                               exit=event["exit_price"], reason=reason, target1_hit=active.target1_hit_at is not None,
                               trailing_activation_r=active.trailing_activation_r,
                               exit_management_profile=active.exit_management_profile,
                               pnl_inr=round(active.pnl, 2)))
            last_close = bar.close_time
            if reason == "STOP":
                cooldown[active.side] = bar.close_time + timedelta(minutes=30)
            active = None
    wins = sum(item["pnl_inr"] > 0 for item in trades)
    gains = sum(max(0, item["pnl_inr"]) for item in trades)
    losses = -sum(min(0, item["pnl_inr"]) for item in trades)
    return dict(closed_trades=len(trades), wins=wins, losses=sum(t["pnl_inr"] < 0 for t in trades),
                win_rate=round(wins/len(trades)*100, 2) if trades else None,
                pnl_inr=round(equity-CAPITAL, 2), profit_factor=round(gains/losses, 3) if losses else None,
                realized_drawdown_percent=round(drawdown, 3), open_positions=int(active is not None),
                censored_positions=censored, target1_hits=sum(t["target1_hit"] for t in trades),
                target2_exits=sum(t["reason"] == "TARGET2" for t in trades),
                stop_exits=sum(t["reason"] == "STOP" for t in trades),
                skipped=dict(skipped), trades=trades[-100:], trade_detail_limit=100)


def build_strategy_comparison(db, symbol, days, now=None):
    end = now or datetime.utcnow()
    start = end - timedelta(days=days)
    rows = (db.query(DecisionSnapshot, PipelineRun.completed_at).outerjoin(
        PipelineRun, PipelineRun.generation_id == DecisionSnapshot.data_generation_id).filter(
        DecisionSnapshot.symbol == symbol, DecisionSnapshot.effective_timestamp >= start,
        DecisionSnapshot.effective_timestamp <= end, DecisionSnapshot.created_at <= end,
        DecisionSnapshot.strategy_id.isnot(None), DecisionSnapshot.timeframe.in_(TIMEFRAMES))
        .order_by(DecisionSnapshot.effective_timestamp, DecisionSnapshot.id).limit(LIMIT+1).all())
    bars = (db.query(MarketCandle).filter(
        MarketCandle.symbol == symbol, MarketCandle.timeframe == "5m", MarketCandle.market_type == "FUTURES",
        MarketCandle.is_final.is_(True), MarketCandle.quality_state.in_(("VERIFIED", "RECONCILED")),
        MarketCandle.open_time >= start, MarketCandle.close_time <= end)
        .order_by(MarketCandle.open_time, MarketCandle.id).limit(LIMIT+1).all())
    if len(rows) > LIMIT or len(bars) > LIMIT:
        raise ValueError("Comparison exceeds 60,000 records; select a shorter period. No results were truncated.")
    # One venue per report: never stitch conflicting exchange candles together.
    venues = Counter(bar.venue for bar in bars if bar.venue not in (None, "UNKNOWN", ""))
    venue = sorted(venues, key=lambda value: (-venues[value], value))[0] if venues else None
    bars = [bar for bar in bars if venue and bar.venue == venue and
            all(_number(getattr(bar, key)) is not None and getattr(bar, key) > 0 for key in ("open_price", "high_price", "low_price", "close_price")) and
            bar.low_price <= min(bar.open_price, bar.close_price) <= max(bar.open_price, bar.close_price) <= bar.high_price]
    groups, exclusions, counts = {}, Counter(), Counter()
    definitions = strategy_definitions(db)
    labels = {(item["id"], item["version"]): item["name"] for item in definitions}
    for row, completed_at in rows:
        if row.strategy_version:
            key = (row.strategy_id, row.strategy_version)
            labels.setdefault(key, row.strategy_id.replace("_", " ").title())
            counts[key] += 1
            # Snapshot rows can be updated to a later generation. Its completion
            # bounds availability; missing/pruned lineage cannot be proven safe.
            if completed_at is None or completed_at > end:
                exclusions[key] += 1
                continue
            item = _decision(row, completed_at)
            if item and item["time"] <= end:
                groups.setdefault(key, []).append(item)
            else:
                exclusions[key] += 1
    results = []
    for (strategy_id, version), name in labels.items():
        decisions = groups.get((strategy_id, version), [])
        metrics = replay_version(decisions, bars)
        status = "NO_DECISION_HISTORY" if not counts[(strategy_id, version)] else "NO_REPLAYABLE_DECISIONS" if not decisions else "NO_PRICE_HISTORY" if not bars else "INCOMPLETE" if metrics["censored_positions"] else "REPLAYED"
        results.append(dict(strategy_id=strategy_id, version=version, name=name, status=status,
                            excluded_decisions=exclusions[(strategy_id, version)],
                            decisions=len(decisions), eligible_decisions=sum(d["decision"] == "ELIGIBLE" for d in decisions), **metrics))
    return dict(source=ENGINE, replay_policy_version=REPLAY_POLICY_VERSION,
                symbol=symbol, start=start.isoformat()+"Z", end=end.isoformat()+"Z",
                initial_capital_inr=CAPITAL, notional_percent=85, fee_bps_per_side=DEFAULT_FEE_BPS,
                venue=venue, price_bars=len(bars), timeframe="5m", results=results,
                price_coverage_percent=round(min(100, len(bars)/(days*288)*100), 2),
                first_price_at=bars[0].open_time.isoformat()+"Z" if bars else None,
                last_price_at=bars[-1].close_time.isoformat()+"Z" if bars else None,
                limitations=["Recorded decision replay, not regeneration of current strategy rules or an out-of-sample validation.",
                             "Each version has independent INR 200,000 capital and 85% unleveraged virtual notional; one position per coin across timeframes.",
                             "Next-bar entry with simulated slippage; recorded level distances rebased to the new fill. Requires a new recorded decision after exit.",
                             "Recorded trailing activation is honored. Missing legacy activation retains legacy immediate trailing; it is not recorded 0R evidence. Named experiment profiles require explicit matching activation metadata.",
                             "Entry structure and fresh-mark entry-quality gates are NOT revalidated at the replay fill. Recorded eligibility is replayed as-is; 5-minute OHLC cannot reconstruct the original fresh scan/mark lifecycle. Missing historical structure evidence is not regenerated.",
                             "Fees and slippage included; funding, INR/USDT exchange-rate changes and shared account risk limits are NOT modeled.",
                             "5-minute OHLC cannot reproduce tick-level trailing stops. Stop-first collisions; stop updates apply next bar.",
                             "Missing exit candles censor the position and stop that version's replay. End-of-window open positions are excluded from closed PNL.",
                             "Drawdown is realized-only. Historical input availability and candle revisions limit comparability; no live approval or automatic tuning."])
