import json
from datetime import datetime

from fastapi import APIRouter, Query
from app.contracts.bundle import IntelligenceBundleResponse

from app.api.v1.ai_scores_api import build_ai_scores_payload
from app.api.v1.derivatives_api import build_derivatives_payload
from app.api.v1.market_api import build_market_candles_payload
from app.api.v1.orderflow_api import build_orderflow_payload
from app.api.v1.risk_api import build_risk_payload
from app.api.v1.signals_api import build_entry_trigger_payload
from app.api.v1.signals_api import build_multi_timeframe_context
from app.api.v1.signals_api import build_multi_timeframe_signal_payload
from app.api.v1.signals_api import build_signal_diagnostics_payload
from app.api.v1.signals_api import build_signal_payload
from app.api.v1.signals_api import build_trade_setup_payload
from app.api.v1.smc_api import build_smc_payload
from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.intelligence.master_ai_engine import generate_master_signal
from app.repositories.candle_repository import get_latest_candle
from app.features.point_in_time_feature_service import build_point_in_time_bundle
from app.repositories.intelligence_repository import get_ai_inputs
from app.repositories._db_utils import safe_rollback
from app.trading.trade_plan_engine import build_trade_plan
from app.utils.freshness import candle_freshness_timestamp, freshness_status
from app.utils.network_resilience import summarize_network_error


router = APIRouter(prefix="/intelligence", tags=["Intelligence"])


def _bundle_section(db, label, builder, failures, *args, **kwargs):
    try:
        return builder(*args, **kwargs)
    except Exception as exc:
        safe_rollback(db)
        failures.append(
            {
                "section": label,
                "error": summarize_network_error(exc),
            }
        )
        return {
            "source": label,
            "status": "FAILED",
            "error": summarize_network_error(exc),
        }


def _build_market_candles_section(db, symbol, timeframe, stale_after_seconds):
    return build_market_candles_payload(db, symbol, timeframe, 80, stale_after_seconds)


def _build_orderflow_section(db, symbol, timeframe, stale_after_seconds):
    return build_orderflow_payload(db, symbol, timeframe, 20, stale_after_seconds)


def _build_smc_section(db, symbol, timeframe, stale_after_seconds):
    return build_smc_payload(db, symbol, timeframe, 20, stale_after_seconds)


def _build_risk_section(db, symbol, stale_after_seconds):
    return build_risk_payload(db, symbol, stale_after_seconds)


def _build_ai_scores_section(db, symbol, timeframe, stale_after_seconds):
    return build_ai_scores_payload(db, symbol, timeframe, 20, stale_after_seconds)


def _build_derivatives_section(db, symbol, stale_after_seconds):
    return build_derivatives_payload(
        db,
        symbol,
        funding_limit=30,
        open_interest_limit=30,
        stale_after_seconds=stale_after_seconds,
    )


def _snapshot_payload(record, kind):
    if not record:
        return None

    return {
        "id": record.id,
        "kind": kind,
        "symbol": record.symbol,
        "timeframe": record.timeframe,
        "source_timestamp": record.source_timestamp,
        "effective_timestamp": record.effective_timestamp,
        "feature_version": getattr(record, "feature_version", None),
        "decision_version": getattr(record, "decision_version", None),
        "quality_state": getattr(record, "quality_state", None),
        "snapshot": json.loads(getattr(record, "snapshot_json", "{}") or "{}"),
    }


@router.get("/{symbol}/snapshot")
def get_intelligence_snapshot(
    symbol: str,
    timeframe: str = Query(default="5m"),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        candle = get_latest_candle(db, symbol, timeframe)

        if not candle:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": "NO_DATA",
                "freshness": freshness_status(None, stale_after_seconds),
            }

        inputs = get_ai_inputs(db, symbol, timeframe)
        signal = generate_master_signal(
            inputs["feature"], inputs["regime"], inputs["orderflow"], inputs["smc"]
        )
        current_price = float(candle.close_price)
        atr = getattr(inputs["feature"], "ATR", None) or current_price * 0.01

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "candle_time": candle.candle_time,
            "freshness": freshness_status(
                candle_freshness_timestamp(candle),
                stale_after_seconds,
            ),
            "signal": signal,
            "trade_plan": build_trade_plan(
                signal["signal"],
                current_price,
                atr,
                confidence=signal["confidence"],
            ),
            "inputs": {
                "feature": freshness_status(
                    getattr(inputs["feature"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "regime": freshness_status(
                    getattr(inputs["regime"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "orderflow": freshness_status(
                    getattr(inputs["orderflow"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "smc": freshness_status(
                    getattr(inputs["smc"], "created_at", None),
                    stale_after_seconds,
                ),
            },
        }

    except Exception:
        safe_rollback(db)
        raise

    finally:
        db.close()


@router.get("/{symbol}/as-of")
def get_intelligence_snapshot_as_of(
    symbol: str,
    timeframe: str = Query(default="5m"),
    as_of: datetime = Query(...),
):
    db = SessionLocal()

    try:
        bundle = build_point_in_time_bundle(db, symbol, timeframe, as_of)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "as_of": as_of,
            "source": "point_in_time_snapshot",
            "feature_snapshot": _snapshot_payload(bundle["feature_snapshot"], "feature"),
            "decision_snapshot": _snapshot_payload(bundle["decision_snapshot"], "decision"),
            "thesis_snapshot": bundle["serialized"]["thesis_snapshot"],
            "leakage_diagnostics": bundle["feature_leakage_diagnostics"],
            "thesis_leakage_diagnostics": bundle["thesis_leakage_diagnostics"],
        }

    except Exception:
        safe_rollback(db)
        raise

    finally:
        db.close()


@router.get("/{symbol}/bundle", response_model=IntelligenceBundleResponse)
def get_intelligence_bundle(
    symbol: str,
    timeframe: str = Query(default="1h"),
    mode: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        failures = []

        signal = _bundle_section(
            db,
            "signal",
            build_signal_payload,
            failures,
            db,
            symbol,
            timeframe=timeframe,
            stale_after_seconds=stale_after_seconds,
        )
        diagnostics = _bundle_section(
            db,
            "diagnostics",
            build_signal_diagnostics_payload,
            failures,
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        candles = _bundle_section(
            db,
            "candles",
            _build_market_candles_section,
            failures,
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        orderflow = _bundle_section(
            db,
            "orderflow",
            _build_orderflow_section,
            failures,
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        smc = _bundle_section(
            db,
            "smc",
            _build_smc_section,
            failures,
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        risk = _bundle_section(
            db,
            "risk",
            _build_risk_section,
            failures,
            db,
            symbol,
            stale_after_seconds,
        )
        ai_scores = _bundle_section(
            db,
            "aiScores",
            _build_ai_scores_section,
            failures,
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        derivatives = _bundle_section(
            db,
            "derivatives",
            _build_derivatives_section,
            failures,
            db,
            symbol,
            stale_after_seconds,
        )
        multi_timeframe_context = _bundle_section(
            db,
            "multiTimeframeContext",
            build_multi_timeframe_context,
            failures,
            db,
            symbol,
            mode=mode,
            stale_after_seconds=stale_after_seconds,
        )
        multi_timeframe_context = (
            multi_timeframe_context
            if isinstance(multi_timeframe_context, dict)
            and "stack" in multi_timeframe_context
            else None
        )
        multi_timeframe = _bundle_section(
            db,
            "multiTimeframe",
            build_multi_timeframe_signal_payload,
            failures,
            db,
            symbol,
            mode=mode,
            lower=None,
            middle=None,
            higher=None,
            stale_after_seconds=stale_after_seconds,
            context=multi_timeframe_context,
        )
        trade_setup = _bundle_section(
            db,
            "tradeSetup",
            build_trade_setup_payload,
            failures,
            db,
            symbol,
            mode=mode,
            lower=None,
            middle=None,
            higher=None,
            stale_after_seconds=stale_after_seconds,
            context=multi_timeframe_context,
        )
        entry_trigger = _bundle_section(
            db,
            "entryTrigger",
            build_entry_trigger_payload,
            failures,
            db,
            symbol,
            mode=mode,
            lower=None,
            middle=None,
            higher=None,
            stale_after_seconds=stale_after_seconds,
            context=multi_timeframe_context,
        )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "mode": mode,
            "stale_after_seconds": stale_after_seconds,
            "source": "intelligence_bundle",
            "signal": signal,
            "diagnostics": diagnostics,
            "candles": candles,
            "orderflow": orderflow,
            "smc": smc,
            "risk": risk,
            "aiScores": ai_scores,
            "derivatives": derivatives,
            "multiTimeframe": multi_timeframe,
            "tradeSetup": trade_setup,
            "entryTrigger": entry_trigger,
            "predictionContext": multi_timeframe,
            "prediction": trade_setup,
            "timing": entry_trigger,
            "bundleStatus": "PARTIAL" if failures else "OK",
            "failures": failures,
        }

    except Exception as exc:
        safe_rollback(db)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "mode": mode,
            "stale_after_seconds": stale_after_seconds,
            "source": "intelligence_bundle",
            "signal": None,
            "diagnostics": None,
            "candles": None,
            "orderflow": None,
            "smc": None,
            "risk": None,
            "aiScores": None,
            "derivatives": None,
            "multiTimeframe": None,
            "tradeSetup": None,
            "entryTrigger": None,
            "predictionContext": None,
            "prediction": None,
            "timing": None,
            "bundleStatus": "FAILED",
            "failures": [
                {
                    "section": "bundle",
                    "error": summarize_network_error(exc),
                }
            ],
        }
    finally:
        db.close()
