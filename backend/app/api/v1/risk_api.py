from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from app.contracts.bundle import RiskBundleResponse

from app.api.v1.derivatives_api import build_derivatives_payload
from app.api.v1.paper_trade_api import build_paper_trade_bundle
from app.api.v1.signals_api import build_multi_timeframe_signal_payload
from app.api.v1.signals_api import build_signal_payload
from app.database.sqlserver import SessionLocal
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE
from app.risk.confidence_sizing import confidence_sizing_profile
from app.risk.account_risk import build_account_daily_pnl_snapshot
from app.risk.risk_engine import RiskEngine
from app.trading.futures_cost_model import DEFAULT_FEE_BPS
from app.paper_trading.inr_sizing import PAPER_MAX_POSITION_INR
from app.paper_trading.exit_policy import approval_target_for_policy
from app.repositories.risk_repository import RiskRepository
from app.repositories.automation_settings_repository import automation_settings_payload
from app.repositories.automation_settings_repository import get_automation_settings
from app.repositories.automation_settings_repository import PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT
from app.repositories.automation_settings_repository import PAPER_MAX_OPEN_TRADES
from app.utils.network_resilience import summarize_network_error
from app.utils.freshness import freshness_status
from app.utils.signal_validation import validate_trade_plan_direction

router = APIRouter(prefix="/risk", tags=["Risk"])


repo = RiskRepository()
risk_engine = RiskEngine()


def _risk_error_payload(operation, symbol, exc, stale_after_seconds=900):
    return {
        "symbol": symbol,
        "source": operation,
        "status": "FAILED",
        "decision": "NO_RISK_DECISION",
        "freshness": freshness_status(None, stale_after_seconds),
        "message": "Risk data unavailable",
        "error": summarize_network_error(exc),
    }


def _build_computed_risk(
    signal,
    max_risk_per_trade,
    stale_after_seconds,
    *,
    timeframe=None,
    mode=None,
):
    if not isinstance(signal, dict):
        return None

    trade_plan = signal.get("trade_plan") or {}
    if not isinstance(trade_plan, dict):
        return None

    price = signal.get("current_price") or trade_plan.get("entry")
    atr = trade_plan.get("atr")
    if price is None or atr is None:
        return None

    try:
        result = risk_engine.analyze_trade_plan(
            symbol=signal.get("symbol"),
            side=signal.get("signal"),
            entry=trade_plan.get("entry"),
            stop_loss=trade_plan.get("stop_loss"),
            target1=trade_plan.get("target1"),
            target2=trade_plan.get("target2"),
            confidence=_effective_confidence(signal),
            risk_percent=max_risk_per_trade,
            fee_bps=DEFAULT_FEE_BPS,
            minimum_reward_target=approval_target_for_policy(
                trade_plan.get("exit_policy"),
                trade_plan.get("target1"),
                trade_plan.get("target2"),
            ),
        )
    except Exception:
        return None

    if not isinstance(result, dict):
        return None

    entry_price = result.get("entry")
    stop_loss = result.get("stop_loss")
    result_targets = result.get("targets") or {}
    target1 = result_targets.get("t1")
    target2 = result_targets.get("t2")
    risk_reward = result.get("risk_reward")
    position_size = result.get("position_size")
    confidence = result.get("confidence")

    approved = str(result.get("decision") or "").upper() == "APPROVE"
    message = result.get("reason") or ("Risk engine approved signal" if approved else "Risk engine rejected signal")

    return {
        "symbol": result.get("symbol") or signal.get("symbol"),
        "timeframe": timeframe or signal.get("timeframe"),
        "mode": mode,
        "thesis_id": signal.get("thesis_id"),
        "source": "computed_current",
        "status": "current_valid" if approved else "current_invalid",
        "signal": result.get("signal") or signal.get("signal"),
        "decision": result.get("decision"),
        "entry_price": entry_price if entry_price is not None else trade_plan.get("entry"),
        "stop_loss": stop_loss if stop_loss is not None else trade_plan.get("stop_loss"),
        "target1": target1 if target1 is not None else trade_plan.get("target1"),
        "target2": target2 if target2 is not None else trade_plan.get("target2"),
        "risk_reward": risk_reward if risk_reward is not None else trade_plan.get("risk_reward"),
        "position_size": position_size,
        "risk_percent": result.get("risk_percent"),
        "requested_risk_percent": result.get("requested_risk_percent"),
        "position_tier": result.get("position_tier"),
        "full_size_confidence": result.get("full_size_confidence"),
        "confidence": confidence if confidence is not None else _effective_confidence(signal),
        "freshness": signal.get("freshness") or freshness_status(None, stale_after_seconds),
        "is_valid_trade_plan": approved,
        "is_usable": approved,
        "ignored_reasons": [] if approved else [message],
        "validation_errors": [] if approved else [message],
    }


@router.get("/{symbol}")
def get_risk(symbol: str, stale_after_seconds: int = Query(default=900, ge=1)):
    db = SessionLocal()

    try:
        return build_risk_payload(db, symbol, stale_after_seconds)
    except Exception as exc:
        db.rollback()
        return _risk_error_payload("risk_decisions", symbol, exc, stale_after_seconds)
    finally:
        db.close()


def build_risk_payload(db, symbol, stale_after_seconds=900):
    risk = repo.latest_for_symbol(db, symbol)

    if not risk:

        return {
            "symbol": symbol,
            "source": "risk_decisions",
            "decision": "NO_RISK_DECISION",
            "freshness": freshness_status(None, stale_after_seconds),
            "message": "No persisted risk decision found for symbol",
        }

    validation = validate_trade_plan_direction(
        risk.signal,
        risk.entry_price,
        risk.target1,
    )
    freshness = freshness_status(risk.created_at, stale_after_seconds)
    is_usable = validation["is_valid"] and not freshness["is_stale"]
    reason = _risk_reason(risk)
    sizing_profile = _stored_sizing_profile(risk)

    return {
        "symbol": risk.symbol,
        "thesis_id": getattr(risk, "thesis_id", None),
        "source": "risk_decisions",
        "status": _risk_status(freshness, validation),
        "signal": risk.signal,
        "decision": risk.decision,
        "entry_price": risk.entry_price,
        "stop_loss": risk.stop_loss,
        "target1": risk.target1,
        "target2": risk.target2,
        "risk_reward": risk.risk_reward,
        "position_size": risk.position_size,
        "risk_percent": risk.risk_percent,
        "requested_risk_percent": sizing_profile["requested_risk_percent"],
        "position_tier": sizing_profile["position_tier"],
        "full_size_confidence": risk_engine.FULL_SIZE_CONFIDENCE,
        "confidence": risk.confidence,
        "reason": reason,
        "thesis_id": getattr(risk, "thesis_id", None),
        "created_at": risk.created_at,
        "freshness": freshness,
        "is_valid_trade_plan": validation["is_valid"],
        "is_usable": is_usable,
        "ignored_reasons": _ignored_reasons(freshness, validation, reason, risk.decision),
        "validation_errors": validation["errors"],
    }


def _stored_sizing_profile(risk):
    confidence = _safe_number(getattr(risk, "confidence", None), 0)
    risk_percent = _safe_number(getattr(risk, "risk_percent", None), 1.0)
    profile = confidence_sizing_profile(confidence, risk_percent)
    if str(getattr(risk, "decision", "") or "").upper() != "APPROVE":
        profile["position_tier"] = None
    # Persisted rows contain the effective risk; the requested cap is not stored.
    profile["risk_percent"] = risk_percent
    profile["requested_risk_percent"] = None
    return profile


@router.get("/{symbol}/bundle", response_model=RiskBundleResponse)
def get_risk_bundle(
    symbol: str,
    timeframe: str = Query(default="15m"),
    mode: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
    enabled: bool = Query(default=True),
    locked: bool = Query(default=True),
    emergency_stop: bool = Query(default=False),
    allowed_symbols: str = Query(default="BTCUSDT,ETHUSDT,XRPUSDT,SOLUSDT"),
    max_risk_per_trade: float = Query(default=1.0, ge=0),
    daily_loss_limit: float = Query(default=4.0, ge=0),
    max_open_trades: int = Query(default=4, ge=1),
    max_leverage: int = Query(default=5, ge=1),
    max_position_size: float = Query(default=PAPER_MAX_POSITION_INR, ge=0),
    min_confidence: float = Query(
        default=MIN_ENTRY_CONFIDENCE,
        ge=0,
        le=100,
    ),
    direction: str = Query(default="BOTH"),
):
    db = SessionLocal()

    try:
        signal = build_signal_payload(db, symbol, timeframe=timeframe, stale_after_seconds=stale_after_seconds)
        risk = build_risk_payload(db, symbol, stale_after_seconds=stale_after_seconds)
        computed_risk = _build_computed_risk(
            signal,
            max_risk_per_trade,
            stale_after_seconds,
            timeframe=timeframe,
            mode=mode,
        )
        multi_timeframe = build_multi_timeframe_signal_payload(
            db,
            symbol,
            mode=mode,
            lower=None,
            middle=None,
            higher=None,
            stale_after_seconds=stale_after_seconds,
        )
        derivatives = build_derivatives_payload(
            db,
            symbol,
            stale_after_seconds=stale_after_seconds,
        )
        paper_bundle = build_paper_trade_bundle(db)
        auto = automation_settings_payload(get_automation_settings(db))
        auto_decision = _build_auto_decision(
            auto,
            symbol,
            signal,
            risk,
            computed_risk,
            paper_bundle,
            multi_timeframe,
            derivatives,
        )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "mode": mode,
            "stale_after_seconds": stale_after_seconds,
            "source": "risk_bundle",
            "status": "OK",
            "data_scope": "timeframe",
            "risk": risk,
            "computedRisk": computed_risk,
            "signal": signal,
            "multiTimeframe": multi_timeframe,
            "predictionContext": multi_timeframe,
            "derivatives": derivatives,
            "paperTrades": {
                "performance": paper_bundle.get("performance"),
                "openTrades": paper_bundle.get("openTrades"),
                "closedTrades": paper_bundle.get("closedTrades"),
                "summary": paper_bundle.get("summary"),
            },
            "auto": auto,
            "autoDecision": auto_decision,
        }

    except Exception as exc:
        db.rollback()
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "mode": mode,
            "stale_after_seconds": stale_after_seconds,
            "source": "risk_bundle",
            "status": "FAILED",
            "error": summarize_network_error(exc),
            "data_scope": "timeframe",
            "risk": None,
            "computedRisk": None,
            "signal": None,
            "multiTimeframe": None,
            "predictionContext": None,
            "derivatives": None,
            "paperTrades": {
                "performance": None,
                "openTrades": {},
                "closedTrades": {},
                "summary": None,
            },
            "auto": None,
            "autoDecision": None,
        }

    finally:
        db.close()


def _risk_status(freshness, validation):
    if not freshness["is_stale"] and validation["is_valid"]:
        return "current_valid"

    if freshness["is_stale"] and not validation["is_valid"]:
        return "historical_stale_invalid"

    if freshness["is_stale"]:
        return "historical_stale"

    return "current_invalid"


def _ignored_reasons(freshness, validation, reason=None, decision=None):
    reasons = []

    if str(decision or "").upper() == "REJECT" and reason:
        reasons.append(reason)

    if freshness["is_stale"]:
        reasons.append("Risk decision is stale")

    reasons.extend(validation["errors"])

    return reasons


def _risk_reason(risk):
    stored_reason = getattr(risk, "reason", None)

    if stored_reason:
        return stored_reason

    if str(getattr(risk, "decision", "") or "").upper() != "REJECT":
        return None

    try:
        recomputed = risk_engine.analyze_trade_plan(
            symbol=risk.symbol,
            side=risk.signal,
            entry=risk.entry_price,
            stop_loss=risk.stop_loss,
            target1=risk.target1,
            target2=risk.target2,
            confidence=risk.confidence or 0,
            risk_percent=risk.risk_percent or 1,
            fee_bps=DEFAULT_FEE_BPS,
        )
    except Exception:
        return None

    return recomputed.get("reason")


def _normalize_auto_settings(auto):
    allowed = auto.get("allowedSymbols")
    if isinstance(allowed, str):
        allowed_symbols = [item.strip().upper() for item in allowed.split(",") if item.strip()]
    elif isinstance(allowed, list):
        allowed_symbols = [str(item).strip().upper() for item in allowed if str(item).strip()]
    else:
        allowed_symbols = []

    direction = str(auto.get("direction") or "BOTH").upper()
    if direction not in {"LONG", "SHORT", "BOTH"}:
        direction = "BOTH"

    return {
        "enabled": bool(auto.get("enabled", True)),
        "locked": bool(auto.get("locked", True)),
        "emergencyStop": bool(auto.get("emergencyStop", False)),
        "allowedSymbols": allowed_symbols,
        "maxRiskPerTrade": _safe_number(auto.get("maxRiskPerTrade"), 1.0),
        "maxRiskPerTradeEnabled": bool(
            auto.get("maxRiskPerTradeEnabled", False)
        ),
        "dailyLossLimit": min(
            _safe_number(auto.get("dailyLossLimit"), 4.0),
            PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT,
        ),
        "maxOpenTrades": min(
            int(_safe_number(auto.get("maxOpenTrades"), 4)),
            PAPER_MAX_OPEN_TRADES,
        ),
        "dailyLossLimitEnabled": bool(
            auto.get("dailyLossLimitEnabled", False)
        ),
        "maxOpenTradesEnabled": bool(
            auto.get("maxOpenTradesEnabled", False)
        ),
        "maxLeverage": int(_safe_number(auto.get("maxLeverage"), 5)),
        "maxPositionSize": PAPER_MAX_POSITION_INR,
        "minConfidence": MIN_ENTRY_CONFIDENCE,
        "direction": direction,
    }


def _build_auto_decision(auto, selected_symbol, signal, risk, computed_risk, paper_bundle, multi_timeframe, derivatives):
    signal_side = _signal_side(signal)
    confidence = _effective_confidence(signal)
    stack_state = _timeframe_stack_state(multi_timeframe)
    invalidation = _signal_invalidation_reason(signal)
    open_trades = paper_bundle.get("openTrades", {}).get("records") or []
    closed_trades = paper_bundle.get("closedTrades", {}).get("records") or []
    trade_blockers = []
    coin_blockers = []
    account_blockers = []
    warnings = []
    effective_risk = _preferred_risk(risk, computed_risk)
    futures_context = _futures_context_payload(derivatives)
    account_risk = paper_bundle.get("accountRisk") or build_account_daily_pnl_snapshot(
        open_trades + closed_trades,
        {selected_symbol: signal.get("current_price")},
        daily_loss_limit=auto["dailyLossLimit"],
    )
    account_open_trade_count = int(
        _safe_number(account_risk.get("open_trade_count"), len(open_trades))
    )

    direction_allowed = (
        auto["direction"] == "BOTH"
        or (auto["direction"] == "LONG" and signal_side == "BUY")
        or (auto["direction"] == "SHORT" and signal_side == "SELL")
    )

    if not auto["enabled"]:
        account_blockers.append("Automation paused")
    if auto["locked"]:
        account_blockers.append("Auto trading locked")
    if auto["emergencyStop"]:
        account_blockers.append("Emergency stop active")
    if selected_symbol not in auto["allowedSymbols"]:
        coin_blockers.append("Symbol not in allowlist")
    if not direction_allowed:
        trade_blockers.append("Direction not allowed")
    if signal_side == "WAIT":
        trade_blockers.append("Signal is WAIT")
    if invalidation:
        trade_blockers.append(invalidation)
    if stack_state in {"MIXED_LIGHT", "MIXED_STRONG"}:
        warnings.append("Timeframe stack is mixed")
    if confidence < auto["minConfidence"]:
        trade_blockers.append("Confidence below minimum")
    if (
        auto["maxOpenTradesEnabled"]
        and account_open_trade_count >= auto["maxOpenTrades"]
    ):
        account_blockers.append("Account-wide open trade cap reached")
    if any(
        str(trade.get("symbol") or "").upper() == str(selected_symbol).upper()
        and str(trade.get("status") or "OPEN").upper() == "OPEN"
        for trade in open_trades
    ):
        coin_blockers.append("Active trade already exists for this coin")
    if not futures_context["fundingAvailable"]:
        warnings.append("Futures funding rate unavailable")
    if not futures_context["openInterestAvailable"]:
        warnings.append("Futures open interest unavailable")
    if effective_risk and effective_risk.get("is_usable") is False:
        trade_blockers.append("Risk decision not usable")
    trade_plan = signal.get("trade_plan") or {}
    if trade_plan and _safe_number(trade_plan.get("risk_reward"), 0) < 1:
        trade_blockers.append("Risk reward is weak")
    if _timeframe_conflict_is_hard_block(multi_timeframe, signal_side):
        trade_blockers.append("Higher timeframe conflict is too strong")

    daily_loss = _safe_number(account_risk.get("daily_pnl_percent"), 0)
    if auto["dailyLossLimitEnabled"] and account_risk.get("limit_reached"):
        account_blockers.append("Account-wide daily loss limit reached")

    blocker_scopes = {
        "trade": trade_blockers,
        "coin": coin_blockers,
        "account": account_blockers,
    }
    reasons = account_blockers + coin_blockers + trade_blockers
    allowed = len(reasons) == 0
    reason = (
        "Selected futures contract passes allowlist, direction, confidence, derivatives, and risk checks."
        if allowed
        else f"Automatic execution blocked by {', '.join(reasons)}."
    )

    return {
        "allowed": allowed,
        "reason": reason,
        "reasons": reasons,
        "warnings": warnings,
        "signalSide": signal_side,
        "confidence": confidence,
        "rawConfidence": confidence,
        "stackState": stack_state,
        "dailyLoss": round(daily_loss, 2),
        "accountRisk": account_risk,
        "blockerScopes": blocker_scopes,
        "tradeBlockers": trade_blockers,
        "coinBlockers": coin_blockers,
        "accountBlockers": account_blockers,
        "openTrades": len(open_trades),
        "accountOpenTrades": account_open_trade_count,
        "closedTrades": len(closed_trades),
        "riskDecisionSource": _risk_source_label(risk, computed_risk),
        "marketContext": futures_context,
    }


def _futures_context_payload(derivatives):
    availability = (derivatives or {}).get("availability") or {}
    funding_available = bool(availability.get("funding"))
    open_interest_available = bool(availability.get("open_interest"))
    return {
        "marketType": "FUTURES",
        "instrumentType": "PERPETUAL",
        "venue": "BINANCE_FUTURES",
        "paperExecutionVenue": "COINDCX_INR_M_PAPER",
        "marginCurrency": "INR",
        "fundingAvailable": funding_available,
        "openInterestAvailable": open_interest_available,
        "isReady": funding_available and open_interest_available,
    }


def _signal_side(signal):
    raw_signal = str(signal.get("signal") or "").upper()
    if _signal_invalidation_reason(signal):
        return "WAIT"
    if raw_signal in {"LONG", "BUY"}:
        return "BUY"
    if raw_signal in {"SHORT", "SELL"}:
        return "SELL"
    if raw_signal in {"WAIT", "NO_DATA"}:
        return "WAIT"
    bias = str(signal.get("bias") or "").upper()
    if "LONG" in bias and raw_signal != "WAIT":
        return "BUY"
    if "SHORT" in bias and raw_signal != "WAIT":
        return "SELL"
    return "WAIT"


def _signal_invalidation_reason(signal):
    if not signal:
        return ""

    freshness = signal.get("freshness") or {}
    contradiction = signal.get("contradiction") or {}
    probability = signal.get("probability") or {}

    if freshness.get("is_stale"):
        return "Signal data is stale"
    if str(contradiction.get("status") or "").upper() == "INVALIDATED":
        return contradiction.get("summary") or "Signal invalidated by contradiction engine"
    if contradiction.get("trade_allowed") is False:
        return contradiction.get("summary") or "Trade blocked by contradiction engine"
    if probability.get("actionable") is False:
        return f"Probability engine decision: {str(probability.get('decision') or 'WAIT').upper()}"
    if str(probability.get("decision") or "").upper() == "WAIT" and str(signal.get("signal") or "").upper() != "WAIT":
        return "Probability engine decision: WAIT"

    return ""


def _preferred_risk(persisted_risk, computed_risk):
    if computed_risk and computed_risk.get("is_usable") is True:
        return computed_risk

    if persisted_risk and persisted_risk.get("is_usable") is True:
        return persisted_risk

    return computed_risk or persisted_risk


def _risk_source_label(persisted_risk, computed_risk):
    if computed_risk and computed_risk.get("is_usable") is True:
        return "computed_current"
    if persisted_risk and persisted_risk.get("is_usable") is True:
        return "persisted_current"
    if computed_risk:
        return "computed_current"
    if persisted_risk:
        return "persisted_current"
    return "none"


def _effective_confidence(signal):
    if not signal:
        return 0
    if _signal_invalidation_reason(signal):
        return _safe_number((signal.get("probability") or {}).get("confidence"), 0)
    return _safe_number(signal.get("confidence"), 0)


def _build_open_positions(open_trades, current_price):
    positions = []
    for trade in open_trades:
        entry = _safe_number(trade.get("entry_price"), 0)
        price = _safe_number(current_price, entry)
        pnl = _estimate_pnl_percent(trade.get("side"), entry, price)
        positions.append(
            {
                **trade,
                "current_price": price,
                "unrealized_pnl_percent": pnl,
            }
        )
    return positions


def _estimate_pnl_percent(side, entry, current):
    start = _safe_number(entry, 0)
    now = _safe_number(current, start)
    if not start:
        return 0
    if str(side).upper() == "SHORT":
        return round(((start - now) / start) * 100, 2)
    return round(((now - start) / start) * 100, 2)


def _contains_mixed_bias(multi_timeframe):
    confirmation = ((multi_timeframe or {}).get("confirmation") or {})
    overall_bias = str(confirmation.get("overall_bias") or "").upper()
    return "MIXED" in overall_bias


def _timeframe_stack_state(multi_timeframe):
    confirmation = ((multi_timeframe or {}).get("confirmation") or {})
    return str(confirmation.get("stack_state") or "").upper()


def _timeframe_conflict_is_hard_block(multi_timeframe, signal_side):
    confirmation = ((multi_timeframe or {}).get("confirmation") or {})
    trade_permission = str(confirmation.get("trade_permission") or "").upper()
    stack_state = str(confirmation.get("stack_state") or "").upper()
    signal_side = str(signal_side or "").upper()

    if signal_side == "BUY" and trade_permission == "SHORT_ONLY":
        return True
    if signal_side == "SELL" and trade_permission == "LONG_ONLY":
        return True

    return stack_state == "MIXED_STRONG"


def _sum_within_days(records, days, field="pnl_percent"):
    cutoff = datetime.utcnow() - timedelta(days=days)
    total = 0.0

    for record in records or []:
        timestamp = _to_timestamp(record.get("closed_at") or record.get("opened_at") or record.get("created_at"))
        if timestamp is None or timestamp < cutoff:
            continue
        total += _safe_number(record.get(field), 0)

    return total


def _to_timestamp(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _safe_number(value, fallback=0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback

    return number if number == number else fallback
