from fastapi import APIRouter
from fastapi import Query

from app.database.models.funding_rates import FundingRate
from app.database.models.open_interest import OpenInterest
from app.database.sqlserver import SessionLocal
from app.utils.freshness import freshness_status
from app.utils.network_resilience import summarize_network_error


router = APIRouter(prefix="/derivatives", tags=["Derivatives"])


@router.get("/{symbol}")
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

    return {
        "symbol": symbol,
        "source": "derivatives",
        "funding": {
            "count": len(funding_history),
            "latest": latest_funding,
            "history": funding_history,
        },
        "openInterest": {
            "count": len(open_interest_history),
            "latest": latest_open_interest,
            "latest_change_pct": latest_open_interest_change_pct,
            "history": open_interest_history,
        },
        "latest_funding_rate": latest_funding.get("rate") if latest_funding else None,
        "latest_open_interest": latest_open_interest.get("value") if latest_open_interest else None,
        "latest_open_interest_change_pct": latest_open_interest_change_pct,
    }


def _latest_open_interest_change_pct(history):
    if len(history) < 2:
        return None

    previous = history[-2].get("value")
    latest = history[-1].get("value")

    if previous in (None, 0) or latest is None:
        return None

    return round(((latest - previous) / previous) * 100, 4)
