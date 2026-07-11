from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal

from app.database.models.market_smc import MarketSMCSignal
from app.utils.network_resilience import summarize_network_error
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/smc", tags=["SMC"])


def _smc_error_payload(symbol, timeframe, exc):
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "smc_signals",
        "count": 0,
        "latest": None,
        "records": [],
        "series": [],
        "trend": "UNKNOWN",
        "availability": {"smc": False, "bias": False, "confidence": False},
        "status": "FAILED",
        "error": summarize_network_error(exc),
    }


@router.get("/{symbol}")
def get_smc(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):

    db = SessionLocal()

    try:
        return build_smc_payload(
            db,
            symbol,
            timeframe,
            limit,
            stale_after_seconds,
        )

    except Exception as exc:
        db.rollback()
        return _smc_error_payload(symbol, timeframe, exc)

    finally:
        db.close()


def build_smc_payload(db, symbol, timeframe=None, limit=20, stale_after_seconds=900):
    query = db.query(MarketSMCSignal).filter(MarketSMCSignal.symbol == symbol)

    if timeframe:
        query = query.filter(MarketSMCSignal.timeframe == timeframe)

    records = (
        query.order_by(MarketSMCSignal.created_at.desc())
        .limit(limit)
        .all()
    )
    items = [
        with_freshness(record, "created_at", stale_after_seconds)
        for record in records
    ]
    series = _dedupe_series(
        [
            {
                "series_key": _series_key(item.get("created_at")),
                "label": _series_label(item.get("created_at")),
                "bias": item.get("smc_bias"),
                "confidence": item.get("confidence"),
                "structure": item.get("structure"),
                "bos_type": item.get("bos_type"),
                "choch_type": item.get("choch_type"),
                "order_block_type": item.get("order_block_type"),
                "order_block_price": item.get("order_block_price"),
                "liquidity_sweep": item.get("liquidity_sweep"),
                "sweep_price": item.get("sweep_price"),
            }
            for item in items
        ]
    )
    latest = items[0] if items else None

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "smc_signals",
        "status": "OK",
        "data_scope": "timeframe",
        "count": len(items),
        "latest": latest,
        "records": items,
        "series": series,
        "trend": _smc_trend(items),
        "availability": {
            "smc": bool(items),
            "bias": any(item.get("bias") not in (None, "", "NONE") for item in series),
            "confidence": any(item.get("confidence") is not None for item in series),
        },
        "latest_bias": latest.get("smc_bias") if latest else None,
        "latest_confidence": latest.get("confidence") if latest else None,
        "latest_structure": latest.get("structure") if latest else None,
    }


def _smc_trend(records):
    if len(records) < 2:
        return "UNKNOWN"

    latest = records[0].get("confidence")
    previous = records[1].get("confidence")

    if latest is None or previous is None:
        return "UNKNOWN"
    if latest > previous:
        return "RISING"
    if latest < previous:
        return "FALLING"
    return "FLAT"


def _series_label(value):
    if not value:
        return ""

    return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)


def _dedupe_series(series):
    unique = {}
    for item in series:
        unique[item.get("series_key") or item.get("label") or ""] = item
    return list(unique.values())


def _series_key(value):
    if not value:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
