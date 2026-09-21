"""Isolated forward paper ledger. Public data in, simulated accounting out."""
import json
from decimal import Decimal, ROUND_DOWN

import pandas as pd

from app.backtesting.spot_execution_probe import levels, sweep
from app.backtesting.spot_pullback_research import ResearchConfig, entry_plan

VERSION = "SPOT_RANGE_FORWARD_PAPER_V1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
CONFIG = ResearchConfig(risk_fraction=.001)
FEE, SLIP = .001, .0005


def initial_state(now, code_hash):
    return {"version": VERSION, "code_hash": code_hash, "created_at": now.isoformat(),
            "cash": 10000., "equity": 10000., "peak": 10000., "day_start": 10000.,
            "week_start": 10000., "day": None, "week": None, "daily_entries": 0,
            "consecutive_stops": 0, "positions": {}, "seen_signals": {}, "cooldown": {},
            "last_cycle": None, "last_books": {}, "halt": None, "daily_halt": False,
            "manual_pause": False, "closed_trades": 0, "wins": 0, "net_pnl": 0.,
            "last_decisions": {}, "live_execution_enabled": False}


def round_quantity(quantity, metadata):
    rule = next(f for f in metadata["filters"] if f["filterType"] == "LOT_SIZE")
    step = Decimal(rule["stepSize"])
    if step <= 0:
        raise ValueError("Invalid lot size")
    q = (Decimal(str(quantity)) / step).to_integral_value(rounding=ROUND_DOWN) * step
    if q <= 0 or q < Decimal(rule["minQty"]) or q > Decimal(rule["maxQty"]):
        raise ValueError("Lot size outside venue bounds")
    return float(q)


def notional_ok(quantity, price, metadata):
    value = quantity * price
    for rule in metadata["filters"]:
        if rule["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
            if value < float(rule["minNotional"]):
                return False
            if "maxNotional" in rule and value > float(rule["maxNotional"]):
                return False
    return True


def paper_cycle(state, now, books, features, metadata, recovered_bars):
    """Pure deterministic cycle; caller serializes updates in a DB transaction.

    books hold locally timed REST snapshots. No order adapter is reachable.
    recovered completed candles provide conservative stop checks between polls.
    """
    state = json.loads(json.dumps(state))
    events = []
    def event(kind, **payload):
        events.append({"time": now.isoformat(), "kind": kind, **payload})
    if state["last_cycle"] and (now - pd.Timestamp(state["last_cycle"])).total_seconds() > 60:
        if state["halt"] is None:
            event("MONITORING_GAP", previous_cycle=state["last_cycle"])
        state["halt"] = state["halt"] or "MONITORING_GAP"
    valid = {}
    for symbol in SYMBOLS:
        snapshot = books.get(symbol)
        try:
            if snapshot is None or not 0 <= (now - pd.Timestamp(snapshot["received_at"])).total_seconds() <= 10:
                raise ValueError("Stale/missing book")
            if snapshot["latency_seconds"] > 3:
                raise ValueError("Slow book request")
            book = snapshot["book"]
            bid, ask = levels(book["bids"], True), levels(book["asks"], False)
            if bid[0][0] >= ask[0][0]:
                raise ValueError("Crossed book")
            old = state["last_books"].get(symbol)
            if old and book["lastUpdateId"] <= old["id"]:
                raise ValueError("Nonincreasing book update ID")
            valid[symbol] = (bid, ask)
            state["last_books"][symbol] = {"id": book["lastUpdateId"], "bid": float(bid[0][0]),
                                                  "time": now.isoformat()}
        except (KeyError, ValueError, TypeError) as exc:
            event("BOOK_REJECTED", symbol=symbol, reason=str(exc))
    def equity():
        return state["cash"] + sum(p["quantity"] * state["last_books"][s]["bid"] * (1-SLIP)*(1-FEE)
                                   for s, p in state["positions"].items())
    marked = equity()
    day = str(now.date())
    week = f"{now.isocalendar().year}-{now.isocalendar().week}"
    if day != state["day"]:
        state.update(day=day, day_start=state["equity"], daily_entries=0, consecutive_stops=0, daily_halt=False)
    if week != state["week"]:
        state.update(week=week, week_start=state["equity"])
    state["peak"] = max(state["peak"], marked)
    if len(valid) == len(SYMBOLS):
        if marked <= state["peak"] * .95:
            state["halt"] = "DRAWDOWN_LIMIT"
        elif marked <= state["week_start"] * .97:
            state["halt"] = "WEEKLY_LOSS_LIMIT"
        elif marked <= state["day_start"] * .99:
            state["daily_halt"] = True

    for symbol, position in list(state["positions"].items()):
        if symbol not in valid:
            continue
        bid_levels, _ = valid[symbol]
        reference = float(bid_levels[0][0])
        reason, evidence = None, "OBSERVED_BOOK_SIMULATION"
        # Only whole bars starting AFTER entry are eligible; no pre-entry lows.
        last_reconciled = pd.Timestamp(position.get("reconciled_until", position["entry_time"]))
        for bar in recovered_bars.get(symbol, []):
            if pd.Timestamp(bar["time"]) >= pd.Timestamp(position["entry_time"]) and pd.Timestamp(bar["end"]) > last_reconciled:
                position["reconciled_until"] = bar["end"]
                if bar["low"] <= position["stop"]:
                    reason, evidence = "STOP", "CONSERVATIVE_CANDLE_RECONCILIATION"
                    reference = min(reference, bar["open"], position["stop"])
                    break
        feature = features.get(symbol)
        if reference <= position["stop"]:
            reason = "STOP"
        elif reason is None and (state["halt"] in ("DRAWDOWN_LIMIT", "WEEKLY_LOSS_LIMIT") or state["daily_halt"]):
            reason = "ACCOUNT_LOSS_LIMIT"
        elif reason is None and reference >= position["target"]:
            reason = "TARGET"
        elif reason is None and now >= pd.Timestamp(position["entry_time"]) + pd.Timedelta(hours=24):
            reason = "TIME_EXIT"
        elif reason is None and feature and now - pd.Timestamp(feature["available_at"]) <= pd.Timedelta(minutes=17) and feature["trend_exit"]:
            reason = "RANGE_BREAK"
        if reason:
            try:
                displayed = float(sweep(bid_levels, Decimal(str(position["quantity"])))) / position["quantity"]
            except ValueError:
                state["halt"] = "INSUFFICIENT_EXIT_DEPTH"
                event("EXIT_BLOCKED", symbol=symbol, reason=state["halt"])
                continue
            fill = min(reference, displayed) * (1-SLIP)
            fee = fill * position["quantity"] * FEE
            proceeds = fill * position["quantity"] - fee
            pnl = proceeds - position["quantity"] * position["entry"] - position["entry_fee"]
            state["cash"] += proceeds
            state["closed_trades"] += 1
            state["wins"] += int(pnl > 0)
            state["net_pnl"] += pnl
            del state["positions"][symbol]
            if reason == "STOP":
                state["cooldown"][symbol] = (now + pd.Timedelta(hours=1)).isoformat()
                state["consecutive_stops"] += 1
            else:
                state["consecutive_stops"] = 0
            event("PAPER_EXIT", symbol=symbol, position=position, exit_price=fill, exit_fee=fee,
                  reason=reason, evidence=evidence, net_pnl=pnl,
                  book_evidence=books[symbol],
                  loss_review="ORDINARY_LOSS_OR_UNKNOWN" if reason == "STOP" else None,
                  automatic_strategy_change_allowed=False)
    if state["consecutive_stops"] >= 3:
        state["daily_halt"] = True
    marked = equity()
    if marked <= state["peak"] * .95:
        state["halt"] = "DRAWDOWN_LIMIT"
    elif marked <= state["week_start"] * .97:
        state["halt"] = "WEEKLY_LOSS_LIMIT"
    elif marked <= state["day_start"] * .99:
        state["daily_halt"] = True

    for symbol in sorted(SYMBOLS, key=lambda s: (-features.get(s, {}).get("turnover", 0), s)):
        feature = features.get(symbol)
        if feature is None:
            continue
        signal_time = feature["available_at"]
        if state["seen_signals"].get(symbol) == signal_time:
            continue
        # Log every completed hourly opportunity once; do not backfill entries.
        if pd.Timestamp(signal_time).minute != 0:
            continue
        state["seen_signals"][symbol] = signal_time
        reason = None
        if not feature["signal"]:
            reason = "NO_SETUP"
        elif not 0 <= (now - pd.Timestamp(signal_time)).total_seconds() <= 90 or pd.Timestamp(signal_time) <= pd.Timestamp(state["created_at"]):
            reason = "STALE_OR_PRESTART_SIGNAL"
        elif state["halt"] or state["manual_pause"] or state["daily_halt"]:
            reason = "ACCOUNT_PAUSED"
        elif len(valid) != len(SYMBOLS) or len(features) != len(SYMBOLS):
            reason = "INCOMPLETE_MARKET_DATA"
        elif symbol in state["positions"] or len(state["positions"]) >= 2 or state["daily_entries"] >= 3:
            reason = "POSITION_OR_DAILY_CAP"
        elif symbol in state["cooldown"] and pd.Timestamp(signal_time) <= pd.Timestamp(state["cooldown"][symbol]):
            reason = "STOP_COOLDOWN"
        elif metadata.get(symbol, {}).get("status") != "TRADING" or not metadata.get(symbol, {}).get("isSpotTradingAllowed", False):
            reason = "INSTRUMENT_UNAVAILABLE"
        if reason is None:
            bid, ask = valid[symbol]
            spread = float((ask[0][0] - bid[0][0]) / ((ask[0][0] + bid[0][0])/2) * 10000)
            if spread > 10:
                reason = "SPREAD"
            else:
                price_rule = next((f for f in metadata[symbol]["filters"] if f["filterType"] == "PRICE_FILTER"), None)
                if price_rule is None or float(price_rule["tickSize"]) <= 0:
                    event("DECISION", symbol=symbol, reason="MISSING_PRICE_FILTER", signal_time=signal_time)
                    continue
                tick = Decimal(price_rule["tickSize"])
                feature = dict(feature)
                for key in ("stop", "fixed_target"):
                    feature[key] = float((Decimal(str(feature[key])) / tick).to_integral_value(rounding=ROUND_DOWN) * tick)
                marked = equity()
                gross = sum(p["quantity"] * state["last_books"][s]["bid"] for s, p in state["positions"].items())
                plan, reason = entry_plan(feature, float(ask[0][0]), marked, state["cash"],
                    sum(p["risk_budget"] for p in state["positions"].values()), CONFIG, gross)
                if plan:
                    try:
                        quantity = round_quantity(plan["quantity"], metadata[symbol])
                        raw_fill = float(sweep(ask, Decimal(str(quantity)))) / quantity
                        # Recheck admission/size at depth-weighted price, not top ask.
                        plan, reason = entry_plan(feature, raw_fill, marked, state["cash"],
                            sum(p["risk_budget"] for p in state["positions"].values()), CONFIG, gross)
                        if plan:
                            quantity = min(quantity, round_quantity(plan["quantity"], metadata[symbol]))
                            if not notional_ok(quantity, plan["entry"], metadata[symbol]):
                                reason = "MIN_MAX_NOTIONAL"
                            else:
                                factor = quantity / plan["quantity"]
                                plan.update(quantity=quantity, risk_budget=plan["risk_budget"]*factor,
                                            entry_fee=quantity*plan["entry"]*FEE, entry_time=now.isoformat(),
                                            signal_time=signal_time, evidence="DISPLAYED_DEPTH_PLUS_BUFFER_SIMULATION")
                                state["cash"] -= quantity*plan["entry"] + plan["entry_fee"]
                                state["positions"][symbol] = plan
                                state["daily_entries"] += 1
                                event("PAPER_ENTRY", symbol=symbol, position=plan, signal=feature,
                                      book_evidence=books[symbol], instrument_filters=metadata[symbol]["filters"])
                    except (ValueError, KeyError, StopIteration) as exc:
                        reason = "EXECUTION_FILTER: " + str(exc)
        decision = {"signal_time": signal_time, "reason": reason or "PAPER_ENTRY",
                    "signal": feature, "paper_only": True}
        state["last_decisions"][symbol] = decision
        event("DECISION", symbol=symbol, **decision)
    state.update(equity=equity(), last_cycle=now.isoformat(), data_healthy=len(valid)==len(SYMBOLS) and len(features)==len(SYMBOLS))
    state["peak"] = max(state["peak"], state["equity"])
    return state, events
