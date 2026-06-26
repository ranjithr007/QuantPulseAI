from datetime import datetime

from fastapi import APIRouter, Query

from app.database.models.thesis_snapshots import ThesisSnapshot
from app.database.sqlserver import SessionLocal
from app.repositories.trade_thesis_repository import TradeThesisRepository
from app.repositories.trade_thesis_repository import serialize_thesis
from app.repositories.thesis_snapshot_repository import build_thesis_snapshot_leakage_diagnostics
from app.repositories.thesis_snapshot_repository import get_thesis_snapshot_as_of
from app.repositories.thesis_snapshot_repository import serialize_thesis_snapshot
from app.utils.network_resilience import summarize_network_error


router = APIRouter(prefix="/theses", tags=["Theses"])


def _thesis_error_payload(symbol, lifecycle_state, exc):
    return {
        "symbol_filter": symbol,
        "lifecycle_state_filter": lifecycle_state,
        "count": 0,
        "latest": None,
        "records": [],
        "status": "FAILED",
        "error": summarize_network_error(exc),
    }


@router.get("/{symbol}")
def get_trade_theses(
    symbol: str,
    lifecycle_state: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    db = SessionLocal()

    try:
        records = TradeThesisRepository().list_theses(
            db,
            symbol=symbol,
            lifecycle_state=lifecycle_state,
            limit=limit,
        )
        return {
            "symbol_filter": symbol,
            "lifecycle_state_filter": lifecycle_state,
            "count": len(records),
            "latest": records[0] if records else None,
            "records": records,
        }

    except Exception as exc:
        db.rollback()
        return _thesis_error_payload(symbol, lifecycle_state, exc)

    finally:
        db.close()


@router.get("/{symbol}/latest")
def get_latest_trade_thesis(symbol: str):
    db = SessionLocal()

    try:
        thesis = TradeThesisRepository().latest_for_symbol(db, symbol)
        return {
            "symbol_filter": symbol,
            "source": "trade_thesis",
            "latest": None if thesis is None else serialize_thesis(thesis),
        }

    except Exception as exc:
        db.rollback()
        return {
            "symbol_filter": symbol,
            "source": "trade_thesis",
            "latest": None,
            "status": "FAILED",
            "error": summarize_network_error(exc),
        }

    finally:
        db.close()


@router.get("/{symbol}/lineage")
def get_trade_thesis_lineage(symbol: str):
    db = SessionLocal()

    try:
        repo = TradeThesisRepository()
        thesis = repo.latest_for_symbol(db, symbol)
        if thesis is None:
            return {
                "symbol_filter": symbol,
                "source": "trade_thesis_lineage",
                "latest": None,
                "latest_snapshot": None,
                "snapshot_count": 0,
                "lifecycle_match": False,
                "leakage_diagnostics": {
                    "source": "thesis_snapshot_leakage_diagnostics",
                    "status": "PARTIAL",
                    "violations": ["thesis missing"],
                    "thesis_snapshot": {
                        "found": False,
                        "within_as_of": False,
                        "version_matches": False,
                        "expected_version": None,
                        "effective_timestamp": None,
                        "source_timestamp": None,
                        "lag_seconds": None,
                    },
                },
            }

        snapshot_as_of = get_thesis_snapshot_as_of(db, symbol, thesis.updated_at or thesis.created_at)
        snapshot_count = (
            db.query(ThesisSnapshot)
            .filter(ThesisSnapshot.symbol == symbol)
            .count()
        )
        leakage_diagnostics = build_thesis_snapshot_leakage_diagnostics(
            snapshot_as_of,
            thesis.updated_at or thesis.created_at,
        )

        return {
            "symbol_filter": symbol,
            "source": "trade_thesis_lineage",
            "latest": serialize_thesis(thesis),
            "latest_snapshot": serialize_thesis_snapshot(snapshot_as_of),
            "snapshot_count": snapshot_count,
            "lifecycle_match": bool(
                snapshot_as_of
                and snapshot_as_of.lifecycle_state == thesis.lifecycle_state
            ),
            "leakage_diagnostics": leakage_diagnostics,
        }

    except Exception as exc:
        db.rollback()
        return {
            "symbol_filter": symbol,
            "source": "trade_thesis_lineage",
            "latest": None,
            "latest_snapshot": None,
            "snapshot_count": 0,
            "lifecycle_match": False,
            "status": "FAILED",
            "error": summarize_network_error(exc),
        }

    finally:
        db.close()


@router.get("/{symbol}/as-of")
def get_thesis_snapshot_as_of_route(
    symbol: str,
    as_of: datetime = Query(...),
):
    db = SessionLocal()

    try:
        snapshot = get_thesis_snapshot_as_of(db, symbol, as_of)
        leakage_diagnostics = build_thesis_snapshot_leakage_diagnostics(snapshot, as_of)
        return {
            "symbol_filter": symbol,
            "source": "thesis_snapshot",
            "as_of": as_of,
            "latest": serialize_thesis_snapshot(snapshot),
            "leakage_diagnostics": leakage_diagnostics,
        }

    except Exception as exc:
        db.rollback()
        return {
            "symbol_filter": symbol,
            "source": "thesis_snapshot",
            "as_of": as_of,
            "latest": None,
            "status": "FAILED",
            "error": summarize_network_error(exc),
        }

    finally:
        db.close()
