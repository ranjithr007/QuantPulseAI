from datetime import timedelta

from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal

from app.intelligence.contradiction_engine import build_contradiction_report
from app.intelligence.data_quality_ledger import build_data_quality_observability
from app.intelligence.probability_engine import build_probability_profile
from app.repositories.intelligence_repository import get_ai_inputs

from app.intelligence.master_ai_engine import generate_master_signal
from app.trading.trade_plan_engine import build_trade_plan

from app.database.models.market_candles import MarketCandle
from app.repositories.candle_repository import get_latest_candle
from app.trading.trade_plan_engine import risk_level
from app.intelligence.signal_quality_engine import validate_signal
from app.risk.risk_engine import RiskEngine
from app.utils.freshness import candle_freshness_timestamp, freshness_status
from app.utils.network_resilience import summarize_network_error
from app.utils.signal_validation import validate_trade_plan_direction

router = APIRouter(prefix="/master-ai-v2", tags=["Master AI V2"])


@router.get("/{symbol}")
def master_ai(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    return build_master_ai_response(symbol, timeframe, stale_after_seconds)


def build_master_ai_response(symbol: str, timeframe: str, stale_after_seconds: int = 900):

    db = SessionLocal()

    try:

        data = get_ai_inputs(db, symbol, timeframe)
        candle = get_latest_candle(db, symbol, timeframe)

        if not candle:

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": "NO_DATA",
                "confidence": 0,
                "freshness": freshness_status(None, stale_after_seconds),
                "message": "No latest candle found for symbol/timeframe",
                "data_quality": build_data_quality_observability(
                    db,
                    symbol,
                    timeframe,
                    stale_after_seconds,
                    persist=False,
                ),
                "contradiction": build_contradiction_report(
                    db,
                    symbol,
                    timeframe,
                    stale_after_seconds,
                ),
                "probability": build_probability_profile(
                    db,
                    symbol,
                    timeframe,
                    stale_after_seconds,
                ),
            }

        result = generate_master_signal(
            data["feature"], data["regime"], data["orderflow"], data["smc"]
        )
        result["symbol"] = symbol
        result["timeframe"] = timeframe

        current_price = float(candle.close_price)
        atr = _latest_atr(data["feature"], current_price)
        trade = build_trade_plan(
            result["signal"],
            current_price,
            atr,
            confidence=result["confidence"],
            symbol=symbol,
            timeframe=timeframe,
        )
        validation = validate_trade_plan_direction(
            result["signal"], trade["entry"], trade["target1"]
        )

        result["trade_plan"] = trade
        result["trade_plan_validation"] = validation
        result["current_price"] = current_price
        result["candle_time"] = candle.candle_time
        result["freshness"] = freshness_status(
            candle_freshness_timestamp(candle),
            stale_after_seconds,
        )
        result["inputs"] = {
            "feature": freshness_status(
                getattr(data["feature"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "regime": freshness_status(
                getattr(data["regime"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "orderflow": freshness_status(
                getattr(data["orderflow"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "smc": freshness_status(
                getattr(data["smc"], "created_at", None),
                stale_after_seconds,
            ),
        }

        quality = validate_signal(
            result["signal"],
            result["confidence"],
            trade,
            data["regime"],
            data["orderflow"],
            data["smc"],
        )

        result["quality"] = quality
        result["contradiction"] = build_contradiction_report(
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        result["probability"] = build_probability_profile(
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        risk_engine = RiskEngine()
        risk = risk_engine.analyze(
            symbol,
            result["signal"],
            current_price,
            trade["atr"],
            result["confidence"],
        )

        result["risk_management"] = risk
        result["risk"] = risk_level(result["confidence"])
        result["data_quality"] = build_data_quality_observability(
            db,
            symbol,
            timeframe,
            stale_after_seconds,
            persist=False,
        )
        result["fusion_contract"] = build_fusion_contract(
            symbol=symbol,
            timeframe=timeframe,
            result=result,
            candle_time=candle.candle_time,
            stale_after_seconds=stale_after_seconds,
            data=data,
            current_price=current_price,
        )

        return result

    except Exception as exc:
        db.rollback()
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "FAILED",
            "signal": "WAIT",
            "confidence": 0,
            "error": summarize_network_error(exc),
            "freshness": freshness_status(None, stale_after_seconds),
            "trade_plan": None,
            "trade_plan_validation": None,
            "inputs": {},
        }

    finally:

        db.close()


def build_fusion_contract(
    symbol: str,
    timeframe: str,
    result: dict,
    candle_time,
    stale_after_seconds: int,
    data: dict | None = None,
    current_price: float | None = None,
):
    quality = result.get("quality") or {}
    contradiction = result.get("contradiction") or {}
    probability = result.get("probability") or {}
    risk_management = result.get("risk_management") or {}
    trade_plan_validation = result.get("trade_plan_validation") or {}
    signals = result.get("scoring_profile") or {}
    thesis = _build_thesis_preview(symbol, timeframe, result, data or {}, current_price, candle_time)
    scenario = _build_scenario_preview(symbol, timeframe, result, data or {}, probability, current_price)

    block_reasons = []
    if quality.get("decision") == "AVOID":
        block_reasons.extend(quality.get("warnings") or [])
    elif quality.get("decision") == "WAIT_CONFIRMATION":
        block_reasons.extend(quality.get("warnings") or [])
    if contradiction.get("status") and contradiction.get("status") != "OK":
        block_reasons.append("contradiction engine raised a guardrail")
    if trade_plan_validation and not trade_plan_validation.get("is_valid", True):
        block_reasons.extend(trade_plan_validation.get("errors") or [])

    return {
        "source": "master_ai_fusion_contract",
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": result.get("signal"),
        "bias": result.get("bias"),
        "confidence": result.get("confidence"),
        "score": result.get("score"),
        "risk_level": result.get("risk"),
        "quality_decision": quality.get("decision"),
        "entry_block_reason": block_reasons[0] if block_reasons else None,
        "block_reasons": block_reasons,
        "next_review_at": None if candle_time is None else candle_time + timedelta(seconds=stale_after_seconds),
        "review_ttl_seconds": stale_after_seconds,
        "components": signals.get("components", []),
        "data_quality": result.get("data_quality"),
        "probability": probability,
        "contradiction": contradiction,
        "risk_management": risk_management,
        "trade_plan_validation": trade_plan_validation,
        "thesis": thesis,
        "scenario": scenario,
        "missing_components": [
            name
            for name, value in {
                "thesis": thesis,
                "scenario": scenario,
            }.items()
            if value is None
        ],
    }


def _build_thesis_preview(symbol, timeframe, result, data, current_price, candle_time):
    regime = data.get("regime")
    regime_name = getattr(regime, "Regime", None) or getattr(regime, "regime", None)
    confidence = result.get("confidence")
    signal = result.get("signal")
    trade_plan = result.get("trade_plan") or {}

    if signal == "WAIT" and not trade_plan:
        return None

    thesis_key = f"{symbol}:{timeframe}:{signal}:{round(confidence or 0, 2)}"
    return {
        "source": "thesis_preview",
        "thesis_key": thesis_key,
        "symbol": symbol,
        "timeframe": timeframe,
        "title": f"{symbol} {signal} thesis preview",
        "lifecycle_state": "ACTIVE" if signal in {"LONG", "SHORT"} else "DRAFT",
        "source_signal": signal,
        "confidence": confidence,
        "regime": regime_name,
        "entry_timeframe": timeframe,
        "current_price": current_price,
        "candle_time": candle_time,
        "assumptions": {
            "bias": result.get("bias"),
            "signal": signal,
            "risk_level": result.get("risk"),
            "confidence": confidence,
            "regime": regime_name,
        },
        "invalidation": {
            "price": trade_plan.get("stop_loss"),
            "rule": f"Close beyond stop loss for {signal.lower()} thesis" if signal else None,
            "lifecycle_state": "INVALIDATED" if signal in {"LONG", "SHORT"} else "DRAFT",
        },
        "targets": {
            "target1": trade_plan.get("target1"),
            "target2": trade_plan.get("target2"),
            "risk_reward": trade_plan.get("risk_reward"),
        },
    }


def _build_scenario_preview(symbol, timeframe, result, data, probability, current_price):
    probabilities = (probability or {}).get("probabilities") or {}
    trade_plan = result.get("trade_plan") or {}
    primary_name = max(probabilities, key=probabilities.get) if probabilities else "WAIT"
    primary_direction = "LONG" if primary_name == "LONG" else "SHORT" if primary_name == "SHORT" else "WAIT"
    regime = data.get("regime")
    regime_name = getattr(regime, "Regime", None) or getattr(regime, "regime", None)
    signal = result.get("signal")

    if not probabilities and not trade_plan:
        return None

    return {
        "source": "scenario_preview",
        "symbol": symbol,
        "timeframe": timeframe,
        "scenario_type": primary_name,
        "primary_path": {
            "name": primary_name,
            "direction": primary_direction,
            "probability": probabilities.get(primary_name, 0),
            "current_price": current_price,
            "target_price": trade_plan.get("target1"),
            "invalidation_price": trade_plan.get("stop_loss"),
            "reason": (probability or {}).get("reasons", ["Scenario preview from current contract"])[0],
        },
        "paths": [
            {
                "name": "LONG",
                "probability": probabilities.get("LONG", 0),
                "direction": "LONG",
            },
            {
                "name": "SHORT",
                "probability": probabilities.get("SHORT", 0),
                "direction": "SHORT",
            },
            {
                "name": "WAIT",
                "probability": probabilities.get("WAIT", 0),
                "direction": "WAIT",
            },
        ],
        "market_context": {
            "regime": regime_name,
            "signal": signal,
            "current_price": current_price,
        },
        "trade_plan": trade_plan,
    }


def _latest_atr(feature, current_price):
    atr = getattr(feature, "ATR", None) if feature else None

    if atr and atr > 0:
        return float(atr)

    return current_price * 0.01
