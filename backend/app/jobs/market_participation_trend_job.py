from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from app.collectors.binances.spot_market_collector import SpotMarketCollector
from app.collectors.fred_macro_collector import FredMacroCollector
from app.config import get_settings
from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.database.models.liquidations import Liquidation
from app.database.sqlserver import SessionLocal
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.intelligence.market_participation_trend_engine import analyze_spot_stack
from app.intelligence.market_participation_trend_engine import build_market_breadth
from app.intelligence.market_participation_trend_engine import build_market_participation_trend
from app.repositories.derivative_repository import DerivativeRepository
from app.repositories.market_participation_repository import MarketParticipationRepository
from app.repositories.spot_market_repository import SpotMarketRepository
from app.repositories.symbol_repository import SymbolRepository
from app.utils.network_resilience import summarize_network_error
from app.utils.freshness import freshness_status
from app.utils.freshness import normalize_timestamp_to_naive_utc


SPOT_HISTORY_LIMIT = 60
FUNDING_MAX_AGE_SECONDS = 12 * 60 * 60
OPEN_INTEREST_MAX_AGE_SECONDS = 15 * 60
OPEN_INTEREST_CHANGE_LOOKBACK_SECONDS = 60 * 60
LIQUIDATION_EVENT_MAX_AGE_SECONDS = 30 * 60


def run_market_participation_trend_job(*, context=None):
    db = SessionLocal()
    collector = SpotMarketCollector()
    repository = MarketParticipationRepository()
    settings = get_settings()
    generation_id = getattr(context, "generation_id", None)
    try:
        symbols = sorted(
            {
                item.symbol
                for item in SymbolRepository().get_active_symbols(db)
            }
        )
        collected = _collect_spot_candles(
            collector,
            [*symbols, "ETHBTC"],
        )
        spot_candles = {
            symbol: collected.get(symbol, {})
            for symbol in symbols
        }
        spot_stacks = {
            symbol: analyze_spot_stack(symbol, candles)
            for symbol, candles in spot_candles.items()
        }
        breadth = build_market_breadth(spot_stacks)
        ethbtc = analyze_spot_stack(
            "ETHBTC",
            collected.get("ETHBTC", {}),
        )
        raw_spot_rows = [
            row
            for symbol_rows in collected.values()
            for timeframe_rows in symbol_rows.values()
            for row in timeframe_rows
        ]
        stored_spot_rows = SpotMarketRepository().save_many(db, raw_spot_rows)
        external_context = FredMacroCollector(
            settings.fred_api_key,
            timeout_seconds=settings.fred_timeout_seconds,
            cache_seconds=settings.fred_cache_seconds,
        ).collect()

        records = []
        for symbol in symbols:
            trend = build_market_participation_trend(
                spot_stacks[symbol],
                derivatives=_derivative_context(db, symbol),
                breadth=breadth,
                ethbtc=ethbtc,
                liquidation=_liquidation_context(db, symbol),
                external_context=external_context,
            )
            record = repository.save(
                db,
                trend,
                data_generation_id=generation_id,
            )
            records.append(
                {
                    "symbol": symbol,
                    "direction": trend["direction"],
                    "score": trend["score"],
                    "confidence": trend["confidence"],
                    "quality_state": trend["quality_state"],
                    "persisted": record is not None,
                    "id": getattr(record, "id", None),
                }
            )
        return {
            "status": "OK" if all(item["persisted"] for item in records) else "DEGRADED",
            "source": "market_participation_trend_job",
            "count": len(records),
            "spot_rows_stored": stored_spot_rows,
            "breadth": breadth,
            "ethbtc": {
                "status": ethbtc.get("status"),
                "score": ethbtc.get("score"),
            },
            "macro": {
                "provider": external_context.get("provider"),
                "status": external_context.get("status"),
                "macro_score": external_context.get("macro_score"),
                "series_count": external_context.get("series_count"),
                "data_timestamp": external_context.get("data_timestamp"),
                "advisory_only": True,
            },
            "records": records,
        }
    except Exception as exc:
        db.rollback()
        return {
            "status": "DEGRADED",
            "source": "market_participation_trend_job",
            "count": 0,
            "error": summarize_network_error(exc),
        }
    finally:
        db.close()


def _collect_spot_candles(collector, symbols):
    requests = [
        (symbol, timeframe)
        for symbol in symbols
        for timeframe in OFFICIAL_ENTRY_TIMEFRAMES
    ]
    collected = {symbol: {} for symbol in symbols}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                collector.get_klines,
                symbol,
                timeframe,
                limit=SPOT_HISTORY_LIMIT,
            ): (symbol, timeframe)
            for symbol, timeframe in requests
        }
        for future in as_completed(futures):
            symbol, timeframe = futures[future]
            try:
                collected[symbol][timeframe] = future.result()
            except Exception:
                collected[symbol][timeframe] = []
    return collected


def _derivative_context(db, symbol, *, as_of_timestamp=None):
    history = DerivativeRepository().history_through(db, symbol, limit=2)
    funding_rows = history.get("funding") or []
    oi_rows = history.get("open_interest") or []
    funding_timestamp = (
        getattr(funding_rows[-1], "funding_time", None) if funding_rows else None
    )
    oi_timestamp = getattr(oi_rows[-1], "timestamp", None) if oi_rows else None
    funding_freshness = freshness_status(
        funding_timestamp,
        FUNDING_MAX_AGE_SECONDS,
        reference_timestamp=as_of_timestamp,
    )
    open_interest_freshness = freshness_status(
        oi_timestamp,
        OPEN_INTEREST_MAX_AGE_SECONDS,
        reference_timestamp=as_of_timestamp,
    )
    funding_rate = (
        float(funding_rows[-1].rate)
        if funding_rows
        and funding_rows[-1].rate is not None
        and not funding_freshness["is_stale"]
        else None
    )
    oi_change = None
    previous_oi_freshness = freshness_status(
        getattr(oi_rows[-2], "timestamp", None) if len(oi_rows) >= 2 else None,
        OPEN_INTEREST_CHANGE_LOOKBACK_SECONDS,
        reference_timestamp=oi_timestamp or as_of_timestamp,
    )
    if (
        len(oi_rows) >= 2
        and not open_interest_freshness["is_stale"]
        and not previous_oi_freshness["is_stale"]
    ):
        previous = float(oi_rows[-2].value or 0)
        current = float(oi_rows[-1].value or 0)
        if previous:
            oi_change = ((current - previous) / previous) * 100
    complete = funding_rate is not None and oi_change is not None
    return {
        "funding_rate": funding_rate,
        "open_interest_change_percent": oi_change,
        "source": "BINANCE_USDT_FUTURES",
        "status": "READY" if complete else "DEGRADED",
        "freshness": {
            "funding": funding_freshness,
            "open_interest": open_interest_freshness,
            "open_interest_previous": previous_oi_freshness,
        },
    }


def _liquidation_context(db, symbol, *, as_of_timestamp=None):
    latest_event = (
        db.query(Liquidation)
        .filter(Liquidation.symbol == symbol)
        .order_by(Liquidation.event_time.desc(), Liquidation.id.desc())
        .first()
    )
    event_timestamp = getattr(latest_event, "event_time", None)
    event_freshness = freshness_status(
        event_timestamp,
        LIQUIDATION_EVENT_MAX_AGE_SECONDS,
        reference_timestamp=as_of_timestamp,
    )
    if latest_event is None:
        return {
            "status": "UNAVAILABLE",
            "data_quality": "ESTIMATED_OR_MISSING",
            "reason": "No observed liquidation event is stored",
            "freshness": event_freshness,
        }
    if event_freshness["is_stale"]:
        return {
            "status": "STALE",
            "data_quality": "STALE",
            "reason": "Latest observed liquidation event is stale",
            "source_timestamp": event_timestamp,
            "freshness": event_freshness,
        }
    row = (
        db.query(LiquidationHeatmap)
        .filter(LiquidationHeatmap.symbol == symbol)
        .order_by(
            LiquidationHeatmap.created_at.desc(),
            LiquidationHeatmap.id.desc(),
        )
        .first()
    )
    heatmap_timestamp = getattr(row, "created_at", None)
    normalized_heatmap_timestamp = normalize_timestamp_to_naive_utc(
        heatmap_timestamp
    )
    normalized_event_timestamp = normalize_timestamp_to_naive_utc(
        event_timestamp
    )
    if (
        row is not None
        and normalized_heatmap_timestamp is not None
        and normalized_event_timestamp is not None
        and normalized_heatmap_timestamp < normalized_event_timestamp
    ):
        return {
            "status": "PENDING",
            "data_quality": "STALE",
            "reason": "Latest liquidation event is awaiting heatmap refresh",
            "source_timestamp": event_timestamp,
            "heatmap_created_at": heatmap_timestamp,
            "freshness": event_freshness,
        }
    if row is None or not (float(row.above_value or 0) + float(row.below_value or 0)):
        return {
            "status": "UNAVAILABLE",
            "data_quality": "ESTIMATED_OR_MISSING",
            "reason": "Observed liquidation events have not produced a heatmap",
            "source_timestamp": event_timestamp,
            "freshness": event_freshness,
        }
    return {
        "status": "READY",
        "data_quality": "OBSERVED",
        "bias": row.bias,
        "liquidity_above": row.liquidity_above,
        "liquidity_below": row.liquidity_below,
        "above_value": row.above_value,
        "below_value": row.below_value,
        "confidence": row.confidence,
        "created_at": row.created_at,
        "source_timestamp": event_timestamp,
        "freshness": event_freshness,
    }
