from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed

from app.collectors.binances.spot_market_collector import SpotMarketCollector
from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.database.sqlserver import SessionLocal
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.intelligence.market_participation_trend_engine import analyze_spot_stack
from app.intelligence.market_participation_trend_engine import build_market_breadth
from app.intelligence.market_participation_trend_engine import build_market_participation_trend
from app.repositories.derivative_repository import DerivativeRepository
from app.repositories.market_participation_repository import MarketParticipationRepository
from app.repositories.symbol_repository import SymbolRepository
from app.utils.network_resilience import summarize_network_error


SPOT_HISTORY_LIMIT = 60


def run_market_participation_trend_job(*, context=None):
    db = SessionLocal()
    collector = SpotMarketCollector()
    repository = MarketParticipationRepository()
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

        records = []
        for symbol in symbols:
            trend = build_market_participation_trend(
                spot_stacks[symbol],
                derivatives=_derivative_context(db, symbol),
                breadth=breadth,
                ethbtc=ethbtc,
                liquidation=_liquidation_context(db, symbol),
                external_context=None,
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
            "breadth": breadth,
            "ethbtc": {
                "status": ethbtc.get("status"),
                "score": ethbtc.get("score"),
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


def _derivative_context(db, symbol):
    history = DerivativeRepository().history_through(db, symbol, limit=2)
    funding_rows = history.get("funding") or []
    oi_rows = history.get("open_interest") or []
    funding_rate = (
        float(funding_rows[-1].rate)
        if funding_rows and funding_rows[-1].rate is not None
        else None
    )
    oi_change = None
    if len(oi_rows) >= 2:
        previous = float(oi_rows[-2].value or 0)
        current = float(oi_rows[-1].value or 0)
        if previous:
            oi_change = ((current - previous) / previous) * 100
    return {
        "funding_rate": funding_rate,
        "open_interest_change_percent": oi_change,
        "source": "BINANCE_USDT_FUTURES",
    }


def _liquidation_context(db, symbol):
    row = (
        db.query(LiquidationHeatmap)
        .filter(LiquidationHeatmap.symbol == symbol)
        .order_by(
            LiquidationHeatmap.created_at.desc(),
            LiquidationHeatmap.id.desc(),
        )
        .first()
    )
    if row is None or not (float(row.above_value or 0) + float(row.below_value or 0)):
        return {"status": "UNAVAILABLE", "data_quality": "ESTIMATED_OR_MISSING"}
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
    }
