from collections import Counter

from app.backtesting.portfolio_replay import build_portfolio_replay
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES


COMBINED_TIMEFRAME_REPLAY_VERSION = "combined_timeframe_portfolio_replay_v1"
TIMEFRAME_DURABILITY = {"1h": 1, "2h": 2, "4h": 3, "1d": 4}


def build_combined_timeframe_portfolio_replay(
    scope_results,
    *,
    initial_capital=10_000,
):
    """Combine governed timeframe candidates and arbitrate one trade per coin."""

    symbol_results = {}
    source_scope_counts = Counter()
    for raw_scope in list(scope_results or ()):
        scope = dict(raw_scope or {})
        symbol = str(scope.get("symbol") or "").upper()
        timeframe = str(scope.get("timeframe") or "").lower()
        signal = str(scope.get("signal") or "").upper()
        if not symbol:
            raise ValueError("scope result requires a symbol")
        if timeframe not in OFFICIAL_ENTRY_TIMEFRAMES:
            raise ValueError(f"unsupported governed timeframe: {timeframe}")
        if signal not in {"LONG", "SHORT"}:
            raise ValueError("scope result signal must be LONG or SHORT")

        bucket = symbol_results.setdefault(symbol, {"trades": []})
        source_scope_counts[(symbol, timeframe, signal)] += 1
        for raw_trade in list(scope.get("trades") or ()):
            trade = dict(raw_trade)
            compact_trade = {
                key: value
                for key, value in trade.items()
                if key != "timeframe_stack"
            }
            decision_chain = dict(
                dict(trade.get("timeframe_stack") or {}).get("decision_chain")
                or {}
            )
            risk = dict(decision_chain.get("risk") or {})
            master_signal = dict(decision_chain.get("signal") or {})
            bucket["trades"].append(
                {
                    **compact_trade,
                    "symbol": symbol,
                    "entry_timeframe": timeframe,
                    "candidate_signal": signal,
                    "selection_confidence": _first_number(
                        risk.get("confidence"),
                        master_signal.get("confidence"),
                        trade.get("confidence"),
                    ),
                    "candidate_score": _first_number(
                        master_signal.get("score"),
                        trade.get("feature_score"),
                    ),
                    "candidate_risk_reward": _first_number(
                        risk.get("risk_reward"),
                        trade.get("risk_reward"),
                    ),
                }
            )

    per_symbol = {}
    for symbol, result in sorted(symbol_results.items()):
        replay = build_portfolio_replay(
            {symbol: result},
            initial_capital=initial_capital,
            max_open_positions=1,
            max_gross_exposure_percent=10_000,
            max_cluster_exposure_percent=10_000,
        )
        replay["overlap_audit"] = _overlap_audit(replay.get("trades") or ())
        per_symbol[symbol] = replay

    portfolio = build_portfolio_replay(
        symbol_results,
        initial_capital=initial_capital,
        max_open_positions=max(len(symbol_results), 1),
        max_gross_exposure_percent=max(len(symbol_results), 1) * 10_000,
        max_cluster_exposure_percent=10_000,
    )
    portfolio["overlap_audit"] = _overlap_audit(portfolio.get("trades") or ())
    portfolio["strongest_selection_audit"] = _strongest_selection_audit(
        symbol_results,
        portfolio.get("trades") or (),
    )

    candidate_count = sum(
        len(result.get("trades") or ()) for result in symbol_results.values()
    )
    selected_count = int(portfolio.get("total_trades") or 0)
    confidence_tier_audit = _confidence_tier_audit(symbol_results)
    return {
        "engine_version": COMBINED_TIMEFRAME_REPLAY_VERSION,
        "status": (
            "PASS"
            if _portfolio_audits_pass(portfolio)
            and confidence_tier_audit["violation_count"] == 0
            else "FAIL"
        ),
        "core_principle": (
            "SCAN_ALL_TIMEFRAMES_SELECT_STRONGEST_ONE_ACTIVE_TRADE_PER_COIN_"
            "WAIT_FOR_EXIT_THEN_RESCAN"
        ),
        "timeframes": list(OFFICIAL_ENTRY_TIMEFRAMES),
        "symbols": sorted(symbol_results),
        "source_scope_count": len(source_scope_counts),
        "candidate_trade_count": candidate_count,
        "selected_trade_count": selected_count,
        "rejected_trade_count": candidate_count - selected_count,
        "symbol_active_rejections": int(
            dict(portfolio.get("rejection_counts") or {}).get(
                "SYMBOL_ACTIVE_POSITION",
                0,
            )
        ),
        "confidence_tier_audit": confidence_tier_audit,
        "per_symbol": per_symbol,
        "portfolio": portfolio,
    }


def _overlap_audit(trades):
    by_symbol = {}
    violations = []
    for trade in list(trades or ()):
        by_symbol.setdefault(str(trade.get("symbol") or "").upper(), []).append(trade)
    for symbol, records in sorted(by_symbol.items()):
        ordered = sorted(records, key=lambda item: str(item.get("entry_time") or ""))
        previous = None
        for trade in ordered:
            if previous is not None and str(previous.get("exit_time") or "") > str(
                trade.get("entry_time") or ""
            ):
                violations.append(
                    {
                        "symbol": symbol,
                        "active_entry": previous.get("entry_time"),
                        "active_exit": previous.get("exit_time"),
                        "overlapping_entry": trade.get("entry_time"),
                    }
                )
            if previous is None or str(trade.get("exit_time") or "") > str(
                previous.get("exit_time") or ""
            ):
                previous = trade
    return {
        "status": "PASS" if not violations else "FAIL",
        "violation_count": len(violations),
        "violations": violations,
    }


def _strongest_selection_audit(symbol_results, selected_trades):
    candidates = {}
    for symbol, result in dict(symbol_results or {}).items():
        for trade in list(dict(result or {}).get("trades") or ()):
            key = (symbol, str(trade.get("entry_time") or ""))
            candidates.setdefault(key, []).append(trade)

    selected = {
        (str(trade.get("symbol") or "").upper(), str(trade.get("entry_time") or "")): trade
        for trade in list(selected_trades or ())
    }
    contested = 0
    violations = []
    for key, chosen in selected.items():
        pool = candidates.get(key) or []
        if len(pool) < 2:
            continue
        contested += 1
        expected = min(pool, key=_selection_order_key)
        if _candidate_identity(expected) != _candidate_identity(chosen):
            violations.append(
                {
                    "symbol": key[0],
                    "entry_time": key[1],
                    "expected": _candidate_identity(expected),
                    "selected": _candidate_identity(chosen),
                }
            )
    return {
        "status": "PASS" if not violations else "FAIL",
        "contested_entry_count": contested,
        "violation_count": len(violations),
        "violations": violations,
    }


def _selection_order_key(trade):
    return (
        -float(trade.get("selection_confidence") or trade.get("confidence") or 0),
        -float(trade.get("candidate_risk_reward") or trade.get("risk_reward") or 0),
        -TIMEFRAME_DURABILITY.get(
            str(trade.get("entry_timeframe") or "").lower(),
            0,
        ),
        str(trade.get("side") or ""),
    )


def _candidate_identity(trade):
    return {
        "entry_timeframe": trade.get("entry_timeframe"),
        "side": trade.get("side"),
        "confidence": float(
            trade.get("selection_confidence") or trade.get("confidence") or 0
        ),
        "risk_reward": float(
            trade.get("candidate_risk_reward") or trade.get("risk_reward") or 0
        ),
    }


def _portfolio_audits_pass(portfolio):
    return (
        portfolio["overlap_audit"]["violation_count"] == 0
        and portfolio["strongest_selection_audit"]["violation_count"] == 0
    )


def _confidence_tier_audit(symbol_results):
    counts = Counter()
    violations = []
    for symbol, result in dict(symbol_results or {}).items():
        for trade in list(dict(result or {}).get("trades") or ()):
            confidence = float(
                trade.get("selection_confidence") or trade.get("confidence") or 0
            )
            sizing = dict(trade.get("sizing") or {})
            actual_tier = sizing.get("position_tier")
            actual_risk = sizing.get("risk_percent")
            if confidence < 40:
                expected_tier = "BLOCKED"
                expected_risk = None
            elif confidence < 60:
                expected_tier = "MINIMUM"
                expected_risk = 0.5
            else:
                expected_tier = "MAXIMUM"
                expected_risk = 1.0
            counts[expected_tier] += 1
            try:
                normalized_actual_risk = float(actual_risk)
            except (TypeError, ValueError):
                normalized_actual_risk = None
            matches = (
                expected_tier != "BLOCKED"
                and actual_tier == expected_tier
                and normalized_actual_risk == expected_risk
            )
            if not matches:
                violations.append(
                    {
                        "symbol": symbol,
                        "entry_time": trade.get("entry_time"),
                        "entry_timeframe": trade.get("entry_timeframe"),
                        "confidence": confidence,
                        "expected_tier": expected_tier,
                        "expected_risk_percent": expected_risk,
                        "actual_tier": actual_tier,
                        "actual_risk_percent": actual_risk,
                    }
                )
    return {
        "status": "PASS" if not violations else "FAIL",
        "candidate_count": sum(counts.values()),
        "minimum_tier_count": counts["MINIMUM"],
        "maximum_tier_count": counts["MAXIMUM"],
        "below_entry_floor_count": counts["BLOCKED"],
        "violation_count": len(violations),
        "violations": violations,
    }


def _first_number(*values):
    for value in values:
        if value is not None:
            return float(value)
    return 0.0
