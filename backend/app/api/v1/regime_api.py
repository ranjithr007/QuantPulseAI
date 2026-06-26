from fastapi import APIRouter, Query

from app.database.models.market_regimes import MarketRegime
from app.database.sqlserver import SessionLocal
from app.regimes.regime_engine import build_regime_contract
from app.regimes.regime_engine import parse_regime_audit
from app.regimes.regime_engine import regime_catalog
from app.utils.network_resilience import summarize_network_error
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/regime", tags=["Regime"])


def _regime_error_payload(operation, symbol=None, timeframe=None, exc=None):
    base = {
        "source": f"v3_regime_{operation}",
        "status": "FAILED",
        "error": summarize_network_error(exc) if exc is not None else "Unknown regime error",
    }
    if symbol is not None:
        base["symbol"] = symbol
    if timeframe is not None:
        base["timeframe"] = timeframe
    return base


@router.get("/catalog")
def get_regime_catalog():
    try:
        return {
            "source": "v3_regime_catalog",
            **regime_catalog(),
            "regime_contract": build_regime_contract(),
        }
    except Exception as exc:
        return _regime_error_payload("catalog", exc=exc)


@router.get("/{symbol}/summary")
def get_regime_summary(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        records = _load_regime_records(db, symbol, timeframe, limit)
        items = [_regime_payload(record, stale_after_seconds) for record in records]
        latest = items[0] if items else None

        return {
            "source": "v3_regime_summary",
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(items),
            "latest": latest,
            "regime_counts": _count_values(items, "Regime"),
            "transition_counts": _count_transition_values(items),
            "recent_transitions": _recent_transitions(items),
            "regime_contract": build_regime_contract(),
        }

    except Exception as exc:
        db.rollback()
        return {
            **_regime_error_payload("summary", symbol=symbol, timeframe=timeframe, exc=exc),
            "count": 0,
            "latest": None,
            "regime_counts": {},
            "transition_counts": {},
            "recent_transitions": [],
        }

    finally:
        db.close()


@router.get("/{symbol}/diagnostics")
def get_regime_diagnostics(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        records = _load_regime_records(db, symbol, timeframe, limit)
        items = [_regime_payload(record, stale_after_seconds) for record in records]

        return {
            "source": "v3_regime_diagnostics",
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(items),
            "latest": items[0] if items else None,
            "records": items,
        }

    except Exception as exc:
        db.rollback()
        return {
            **_regime_error_payload("diagnostics", symbol=symbol, timeframe=timeframe, exc=exc),
            "count": 0,
            "latest": None,
            "records": [],
        }

    finally:
        db.close()


@router.get("/{symbol}")
def get_regimes(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        records = _load_regime_records(db, symbol, timeframe, limit)

        items = [_regime_payload(record, stale_after_seconds) for record in records]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(items),
            "latest": items[0] if items else None,
            "records": items,
        }

    except Exception as exc:
        db.rollback()
        return {
            **_regime_error_payload("records", symbol=symbol, timeframe=timeframe, exc=exc),
            "count": 0,
            "latest": None,
            "records": [],
        }

    finally:
        db.close()


@router.get("/{symbol}/transitions")
def get_regime_transitions(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        records = _load_regime_records(db, symbol, timeframe, limit)
        items = [_regime_payload(record, stale_after_seconds) for record in records]

        return {
            "source": "v3_regime_transitions",
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(items),
            "latest": items[0] if items else None,
            "transitions": _build_transition_history(items),
        }

    except Exception as exc:
        db.rollback()
        return {
            **_regime_error_payload("transitions", symbol=symbol, timeframe=timeframe, exc=exc),
            "count": 0,
            "latest": None,
            "transitions": [],
        }

    finally:
        db.close()


def _regime_payload(record, stale_after_seconds):
    item = with_freshness(record, "CreatedAt", stale_after_seconds)

    if item is None:
        return None

    item["audit"] = parse_regime_audit(getattr(record, "Reason", None))
    return item


def _load_regime_records(db, symbol, timeframe, limit):
    query = db.query(MarketRegime).filter(MarketRegime.Symbol == symbol)

    if timeframe:
        query = query.filter(MarketRegime.Timeframe == timeframe)

    return query.order_by(MarketRegime.CreatedAt.desc()).limit(limit).all()


def _count_values(items, key):
    counts = {}

    for item in items:
        if not item:
            continue

        value = item.get(key)
        if value is None:
            continue

        counts[value] = counts.get(value, 0) + 1

    return counts


def _count_transition_values(items):
    counts = {}

    for item in items:
        if not item:
            continue

        audit = item.get("audit") or {}
        value = audit.get("transition_decision")
        if value is None:
            continue

        counts[value] = counts.get(value, 0) + 1

    return counts


def _recent_transitions(items):
    recent = []

    for item in items:
        if not item:
            continue

        audit = item.get("audit") or {}
        recent.append(
            {
                "created_at": item.get("CreatedAt"),
                "regime": item.get("Regime"),
                "confidence": item.get("Confidence"),
                "transition_decision": audit.get("transition_decision"),
                "selected_regime": audit.get("selected_regime"),
                "candidate_regime": audit.get("candidate_regime"),
                "dwell_cycles": audit.get("dwell_cycles"),
            }
        )

    return recent


def _build_transition_history(items):
    transitions = []

    for index, item in enumerate(items):
        if not item:
            continue

        audit = item.get("audit") or {}
        previous = items[index + 1] if index + 1 < len(items) else None

        transitions.append(
            {
                "created_at": item.get("CreatedAt"),
                "current_regime": item.get("Regime"),
                "current_confidence": item.get("Confidence"),
                "candidate_regime": audit.get("candidate_regime"),
                "selected_regime": audit.get("selected_regime"),
                "previous_regime": audit.get("previous_regime"),
                "transition_decision": audit.get("transition_decision"),
                "transition_confidence": audit.get("transition_confidence"),
                "dwell_cycles": audit.get("dwell_cycles"),
                "held_previous": audit.get("transition_decision") == "HELD_PREVIOUS",
                "previous_created_at": previous.get("CreatedAt") if previous else None,
            }
        )

    return transitions
