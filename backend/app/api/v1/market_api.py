from fastapi import APIRouter, Query

from app.collectors.binances.candle_collector import CandleCollector
from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.repositories.candle_repository import get_latest_candles
from app.repositories.market_repository import MarketRepository
from app.repositories.symbol_repository import SymbolRepository
from app.utils.freshness import candle_freshness_timestamp, freshness_status
from app.utils.freshness import stale_after_seconds_for_timeframe
from app.utils.freshness import with_freshness
from app.contracts.specialized import MarketCandlesResponse
from app.contracts.control import MarketRefreshResponse


router = APIRouter(prefix="/market", tags=["Market"])
FUTURES_REFRESH_ORDER = ["1d", "4h", "1h", "15m", "5m", "1m"]


@router.get("/{symbol}/candles", response_model=MarketCandlesResponse)
def get_market_candles(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    stale_after_seconds: int | None = Query(default=None, ge=1),
):
    db = SessionLocal()

    try:
        return build_market_candles_payload(
            db,
            symbol,
            timeframe,
            limit,
            stale_after_seconds,
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


@router.post("/{symbol}/refresh-candles", response_model=MarketRefreshResponse)
def refresh_market_candles(
    symbol: str,
    timeframe: str = Query(...),
    limit: int = Query(default=500, ge=50, le=15000),
    replace_existing: bool = Query(default=False),
):
    db = SessionLocal()

    try:
        return _refresh_market_candles_payload(
            db,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            replace_existing=replace_existing,
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


@router.post("/refresh-candles/bulk", response_model=MarketRefreshResponse)
def refresh_market_candles_bulk(
    timeframe: str = Query(...),
    limit: int = Query(default=500, ge=50, le=15000),
    replace_existing: bool = Query(default=False),
    symbols: str | None = Query(default=None),
):
    db = SessionLocal()

    try:
        normalized_timeframe = str(timeframe).strip()
        requested_symbols = _normalize_symbols(symbols)
        if requested_symbols:
            selected_symbols = requested_symbols
        else:
            selected_symbols = [
                item.symbol.upper()
                for item in SymbolRepository().get_active_symbols(db)
            ]

        results = [
            _refresh_market_candles_payload(
                db,
                symbol=item_symbol,
                timeframe=normalized_timeframe,
                limit=limit,
                replace_existing=replace_existing,
            )
            for item_symbol in selected_symbols
        ]

        return {
            "source": "binance_futures_bulk_refresh",
            "market_type": "FUTURES",
            "venue": "BINANCE_FUTURES",
            "timeframe": normalized_timeframe,
            "replace_existing": replace_existing,
            "requested_limit": limit,
            "requested_symbols": requested_symbols,
            "processed_symbols": len(selected_symbols),
            "saved_count": sum(item.get("saved_count", 0) for item in results),
            "skipped_count": sum(item.get("skipped_count", 0) for item in results),
            "fetched_count": sum(item.get("fetched_count", 0) for item in results),
            "results": results,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


@router.post("/refresh-candles/stack", response_model=MarketRefreshResponse)
def refresh_market_candles_stack(
    limit: int = Query(default=500, ge=50, le=15000),
    replace_existing: bool = Query(default=False),
    symbols: str | None = Query(default=None),
):
    db = SessionLocal()

    try:
        requested_symbols = _normalize_symbols(symbols)
        if requested_symbols:
            selected_symbols = requested_symbols
        else:
            selected_symbols = [
                item.symbol.upper()
                for item in SymbolRepository().get_active_symbols(db)
            ]

        timeframe_results = []
        total_fetched = 0
        total_saved = 0
        total_skipped = 0

        for timeframe in FUTURES_REFRESH_ORDER:
            results = [
                _refresh_market_candles_payload(
                    db,
                    symbol=item_symbol,
                    timeframe=timeframe,
                    limit=limit,
                    replace_existing=replace_existing,
                )
                for item_symbol in selected_symbols
            ]
            fetched_count = sum(item.get("fetched_count", 0) for item in results)
            saved_count = sum(item.get("saved_count", 0) for item in results)
            skipped_count = sum(item.get("skipped_count", 0) for item in results)
            total_fetched += fetched_count
            total_saved += saved_count
            total_skipped += skipped_count
            timeframe_results.append(
                {
                    "timeframe": timeframe,
                    "processed_symbols": len(selected_symbols),
                    "fetched_count": fetched_count,
                    "saved_count": saved_count,
                    "skipped_count": skipped_count,
                    "results": results,
                }
            )

        return {
            "source": "binance_futures_stack_refresh",
            "market_type": "FUTURES",
            "venue": "BINANCE_FUTURES",
            "timeframes": FUTURES_REFRESH_ORDER,
            "replace_existing": replace_existing,
            "requested_limit": limit,
            "requested_symbols": requested_symbols,
            "processed_symbols": len(selected_symbols),
            "total_fetched_count": total_fetched,
            "total_saved_count": total_saved,
            "total_skipped_count": total_skipped,
            "timeframe_results": timeframe_results,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


@router.get("/coverage/stack")
def get_market_stack_coverage(
    symbols: str | None = Query(default=None),
):
    db = SessionLocal()

    try:
        requested_symbols = _normalize_symbols(symbols)
        if requested_symbols:
            selected_symbols = requested_symbols
        else:
            selected_symbols = [
                item.symbol.upper()
                for item in SymbolRepository().get_active_symbols(db)
            ]

        records = [
            {
                "symbol": symbol,
                "timeframes": [
                    _market_timeframe_coverage(db, symbol, timeframe)
                    for timeframe in FUTURES_REFRESH_ORDER
                ],
            }
            for symbol in selected_symbols
        ]

        complete_symbols = sum(
            1
            for item in records
            if all(timeframe_item["has_data"] for timeframe_item in item["timeframes"])
        )
        fresh_symbols = sum(
            1
            for item in records
            if all(not timeframe_item["freshness"]["is_stale"] for timeframe_item in item["timeframes"])
        )

        return {
            "source": "binance_futures_stack_coverage",
            "market_type": "FUTURES",
            "venue": "BINANCE_FUTURES",
            "timeframes": FUTURES_REFRESH_ORDER,
            "requested_symbols": requested_symbols,
            "processed_symbols": len(selected_symbols),
            "complete_symbols": complete_symbols,
            "fresh_symbols": fresh_symbols,
            "records": records,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def build_market_candles_payload(db, symbol, timeframe=None, limit=100, stale_after_seconds=None):
    effective_stale_after_seconds = (
        stale_after_seconds
        if stale_after_seconds is not None
        else stale_after_seconds_for_timeframe(timeframe)
    )

    if timeframe:
        records = get_latest_candles(db, symbol, timeframe, limit)
    else:
        records = (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol == symbol)
            .order_by(MarketCandle.candle_time.desc())
            .limit(limit)
            .all()
        )

    items = [
        with_freshness(record, "candle_time", effective_stale_after_seconds)
        for record in records
    ]

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "market_candles",
        "status": "OK",
        "data_scope": "timeframe",
        "count": len(items),
        "latest": items[-1] if items else None,
        "records": items,
    }


def _refresh_market_candles_payload(db, symbol, timeframe, limit, replace_existing):
    normalized_symbol = str(symbol).upper()
    normalized_timeframe = str(timeframe).strip()
    collector = CandleCollector()
    repo = MarketRepository()

    existing_count = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == normalized_symbol)
        .filter(MarketCandle.timeframe == normalized_timeframe)
        .count()
    )

    candles = collector.get_candles(
        normalized_symbol,
        interval=normalized_timeframe,
        limit=limit,
    ) or []

    if replace_existing:
        repo.delete_candles(db, normalized_symbol, normalized_timeframe)

    saved_count = 0
    skipped_count = 0
    latest_candle = None

    for candle in candles:
        inserted = repo.save_candle(db, candle)
        if inserted:
            saved_count += 1
            latest_candle = candle
        else:
            skipped_count += 1

    final_count = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == normalized_symbol)
        .filter(MarketCandle.timeframe == normalized_timeframe)
        .count()
    )

    return {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "source": "binance_futures_refresh",
        "market_type": "FUTURES",
        "venue": "BINANCE_FUTURES",
        "replace_existing": replace_existing,
        "requested_limit": limit,
        "fetched_count": len(candles),
        "existing_count_before": existing_count,
        "saved_count": saved_count,
        "skipped_count": skipped_count,
        "final_count": final_count,
        "latest_refreshed_candle": latest_candle,
    }


def _market_timeframe_coverage(db, symbol, timeframe):
    latest_records = get_latest_candles(db, symbol, timeframe, limit=1)
    latest = latest_records[0] if latest_records else None
    count = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .count()
    )
    freshness = freshness_status(
        candle_freshness_timestamp(latest),
        stale_after_seconds_for_timeframe(timeframe),
    )
    return {
        "timeframe": timeframe,
        "has_data": bool(latest),
        "count": count,
        "latest_candle_time": getattr(latest, "candle_time", None),
        "latest_close": getattr(latest, "close_price", None),
        "freshness": freshness,
    }


def _normalize_symbols(symbols):
    if not symbols:
        return []

    if isinstance(symbols, str):
        symbols = symbols.split(",")

    normalized = []
    seen = set()
    for item in symbols:
        value = str(item).strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    return normalized
