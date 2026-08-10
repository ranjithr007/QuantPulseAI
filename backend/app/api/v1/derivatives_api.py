from fastapi import APIRouter
from fastapi import Query

from app.database.models.funding_rates import FundingRate
from app.database.models.open_interest import OpenInterest
from app.database.sqlserver import SessionLocal
from app.utils.freshness import freshness_status
from app.utils.network_resilience import summarize_network_error
from app.contracts.specialized import DerivativesResponse


router = APIRouter(prefix="/derivatives", tags=["Derivatives"])


@router.get("/{symbol}", response_model=DerivativesResponse)
def get_derivatives(
    symbol: str,
    funding_limit: int = Query(default=30, ge=1, le=200),
    open_interest_limit: int = Query(default=30, ge=1, le=200),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        return build_derivatives_payload(
            db,
            symbol,
            funding_limit=funding_limit,
            open_interest_limit=open_interest_limit,
            stale_after_seconds=stale_after_seconds,
        )
    except Exception as exc:
        db.rollback()
        return {
            "symbol": symbol,
            "source": "derivatives",
            "status": "FAILED",
            "error": summarize_network_error(exc),
            "funding": {"count": 0, "latest": None, "history": []},
            "openInterest": {
                "count": 0,
                "latest": None,
                "latest_change_pct": None,
                "history": [],
            },
            "latest_funding_rate": None,
            "latest_open_interest": None,
            "latest_open_interest_change_pct": None,
            "latestFundingRate": None,
            "latestOpenInterest": None,
            "latestOpenInterestChangePct": None,
            "fundingRateGraph": [],
            "openInterestGraph": [],
        }
    finally:
        db.close()


def build_derivatives_payload(
    db,
    symbol,
    funding_limit=30,
    open_interest_limit=30,
    stale_after_seconds=900,
):
    funding_records = (
        db.query(FundingRate)
        .filter(FundingRate.symbol == symbol)
        .order_by(FundingRate.funding_time.desc(), FundingRate.id.desc())
        .limit(funding_limit)
        .all()
    )
    open_interest_records = (
        db.query(OpenInterest)
        .filter(OpenInterest.symbol == symbol)
        .order_by(OpenInterest.timestamp.desc(), OpenInterest.id.desc())
        .limit(open_interest_limit)
        .all()
    )

    funding_history = [
        {
            "symbol": record.symbol,
            "rate": record.rate,
            "funding_time": record.funding_time,
            "created_at": record.created_at,
        }
        for record in reversed(funding_records)
    ]
    open_interest_history = [
        {
            "symbol": record.symbol,
            "value": record.value,
            "timestamp": record.timestamp,
            "created_at": record.created_at,
        }
        for record in reversed(open_interest_records)
    ]

    latest_funding = funding_history[-1] if funding_history else None
    latest_open_interest = open_interest_history[-1] if open_interest_history else None
    latest_open_interest_change_pct = _latest_open_interest_change_pct(open_interest_history)

    if latest_funding:
        latest_funding["freshness"] = freshness_status(
            latest_funding.get("funding_time"),
            stale_after_seconds,
        )

    if latest_open_interest:
        latest_open_interest["freshness"] = freshness_status(
            latest_open_interest.get("timestamp"),
            stale_after_seconds,
        )

    funding_series = _dedupe_series(
        [
            {
                "series_key": _series_key(item.get("funding_time") or item.get("created_at")),
                "label": _series_label(item.get("funding_time") or item.get("created_at")),
                "value": item.get("rate"),
            }
            for item in funding_history
        ]
    )
    open_interest_series = _dedupe_series(
        [
            {
                "series_key": _series_key(item.get("timestamp") or item.get("created_at")),
                "label": _series_label(item.get("timestamp") or item.get("created_at")),
                "value": item.get("value"),
            }
            for item in open_interest_history
        ]
    )

    return {
        "symbol": symbol,
        "source": "derivatives",
        "status": "OK",
        "data_scope": "symbol",
        "availability": {
            "funding": bool(funding_history),
            "open_interest": bool(open_interest_history),
        },
        "funding": {
            "count": len(funding_history),
            "latest": latest_funding,
            "history": funding_history,
            "series": funding_series,
            "trend": _funding_trend(funding_history),
        },
        "openInterest": {
            "count": len(open_interest_history),
            "latest": latest_open_interest,
            "latest_change_pct": latest_open_interest_change_pct,
            "history": open_interest_history,
            "series": open_interest_series,
            "trend": _open_interest_trend(open_interest_history),
        },
        "latest_funding_rate": latest_funding.get("rate") if latest_funding else None,
        "latest_open_interest": latest_open_interest.get("value") if latest_open_interest else None,
        "latest_open_interest_change_pct": latest_open_interest_change_pct,
        "funding_rate_graph": funding_series,
        "open_interest_graph": open_interest_series,
        "latestFundingRate": latest_funding.get("rate") if latest_funding else None,
        "latestOpenInterest": latest_open_interest.get("value") if latest_open_interest else None,
        "latestOpenInterestChangePct": latest_open_interest_change_pct,
        "fundingRateGraph": funding_series,
        "openInterestGraph": open_interest_series,
        "funding_trend": _funding_trend(funding_history),
        "open_interest_trend": _open_interest_trend(open_interest_history),
    }


def _latest_open_interest_change_pct(history):
    if len(history) < 2:
        return None

    previous = history[-2].get("value")
    latest = history[-1].get("value")

    if previous in (None, 0) or latest is None:
        return None

    return round(((latest - previous) / previous) * 100, 4)


def _funding_trend(history):
    if len(history) < 2:
        return "UNKNOWN"

    latest = history[-1].get("rate")
    previous = history[-2].get("rate")

    if latest is None or previous is None:
        return "UNKNOWN"
    if latest > previous:
        return "RISING"
    if latest < previous:
        return "FALLING"
    return "FLAT"


def _open_interest_trend(history):
    if len(history) < 2:
        return "UNKNOWN"

    latest = history[-1].get("value")
    previous = history[-2].get("value")

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
        key = item.get("series_key") or item.get("label") or ""
        unique[key] = item
    return list(unique.values())


def _series_key(value):
    if not value:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
