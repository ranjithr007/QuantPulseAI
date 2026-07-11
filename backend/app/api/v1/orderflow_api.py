from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal

from app.database.models.market_order_flow import MarketOrderFlow
from app.utils.network_resilience import summarize_network_error
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/orderflow", tags=["Order Flow"])


def _orderflow_error_payload(symbol, timeframe, exc):
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "orderflow",
        "count": 0,
        "latest": None,
        "records": [],
        "series": [],
        "trend": "UNKNOWN",
        "availability": {"orderflow": False, "delta": False, "cvd": False},
        "status": "FAILED",
        "error": summarize_network_error(exc),
    }


@router.get("/{symbol}")
def get_orderflow(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):

    db = SessionLocal()

    try:
        return build_orderflow_payload(
            db,
            symbol,
            timeframe,
            limit,
            stale_after_seconds,
        )

    except Exception as exc:
        db.rollback()
        return _orderflow_error_payload(symbol, timeframe, exc)

    finally:
        db.close()


def build_orderflow_payload(db, symbol, timeframe=None, limit=20, stale_after_seconds=900):
    query = db.query(MarketOrderFlow).filter(MarketOrderFlow.Symbol == symbol)

    if timeframe:
        query = query.filter(MarketOrderFlow.Timeframe == timeframe)

    records = (
        query.order_by(MarketOrderFlow.CreatedAt.desc())
        .limit(limit)
        .all()
    )
    items = [
        with_freshness(record, "CreatedAt", stale_after_seconds)
        for record in records
    ]
    series = _dedupe_series(
        [
            {
                "series_key": _series_key(item.get("CreatedAt")),
                "label": _series_label(item.get("CreatedAt")),
                "buy_volume": item.get("BuyVolume"),
                "sell_volume": item.get("SellVolume"),
                "delta": item.get("Delta"),
                "cvd": item.get("CVD"),
                "buyer_strength": item.get("BuyerStrength"),
                "seller_strength": item.get("SellerStrength"),
                "flow_signal": item.get("FlowSignal"),
                "confidence": item.get("Confidence"),
            }
            for item in items
        ]
    )
    latest = items[0] if items else None

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "orderflow",
        "status": "OK",
        "data_scope": "timeframe",
        "count": len(items),
        "latest": latest,
        "records": items,
        "series": series,
        "trend": _orderflow_trend(items),
        "availability": {
            "orderflow": bool(items),
            "delta": any(item.get("delta") is not None for item in series),
            "cvd": any(item.get("cvd") is not None for item in series),
        },
        "latest_delta": latest.get("Delta") if latest else None,
        "latest_cvd": latest.get("CVD") if latest else None,
        "latest_flow_signal": latest.get("FlowSignal") if latest else None,
    }


def _orderflow_trend(records):
    if len(records) < 2:
        return "UNKNOWN"

    latest = records[0].get("Delta")
    previous = records[1].get("Delta")

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
