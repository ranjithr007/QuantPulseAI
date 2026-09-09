"""Print a read-only matched-entry exit study from the configured database."""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", choices=("strategy", "consolidated"), default="strategy")
    parser.add_argument("--days", type=int, choices=range(1, 31), default=7)
    parser.add_argument("--per-strategy", type=int, choices=range(1, 101), default=30)
    parser.add_argument("--symbol")
    parser.add_argument("--trade-id", type=int)
    args = parser.parse_args()
    # Import after parsing: --help works without DB initialization or credentials.
    from sqlalchemy import text
    from app.database.sqlserver import SessionLocal
    from app.database.models.paper_trade import PaperTrade
    from app.database.models.strategy_shadow_trade import StrategyShadowTrade
    from app.database.models.market_candles import MarketCandle
    from app.backtesting.matched_exit_replay import compare_records

    model = StrategyShadowTrade if args.book == "strategy" else PaperTrade
    end = datetime.utcnow()
    start = end - timedelta(days=args.days)
    fields = ("id", "symbol", "side", "strategy_id", "strategy_version", "opened_at",
              "entry_price", "initial_stop_loss", "target1", "target2", "target1_fraction",
              "position_notional_inr", "max_hold_hours", "exit_policy", "fee_bps")
    with SessionLocal() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
        query = db.query(*(getattr(model, f) for f in fields)).filter(
            model.opened_at >= start, model.opened_at <= end)
        if args.symbol:
            query = query.filter(model.symbol == args.symbol.upper())
        if args.trade_id is not None:
            query = query.filter(model.id == args.trade_id)
        source = query.order_by(model.opened_at.desc(), model.id.desc()).limit(10001).all()
        if len(source) > 10000:
            raise ValueError("More than 10,000 entries: narrow --days or --symbol. No silent truncation.")
        counts, records = {}, []
        for row in source:
            record = SimpleNamespace(**dict(zip(fields, row)))
            key = (record.strategy_id, record.strategy_version)
            if counts.get(key, 0) >= args.per_strategy:
                continue
            counts[key] = counts.get(key, 0) + 1
            records.append(record)
        candles = {}
        for symbol in sorted({r.symbol for r in records}):
            earliest = min(r.opened_at for r in records if r.symbol == symbol) - timedelta(minutes=5)
            columns = ("symbol", "open_time", "close_time", "open_price", "high_price", "low_price", "close_price")
            rows = db.query(*(getattr(MarketCandle, f) for f in columns)).filter(
                MarketCandle.symbol == symbol, MarketCandle.timeframe == "5m",
                MarketCandle.venue == "BINANCE", MarketCandle.market_type == "FUTURES",
                MarketCandle.is_final.is_(True), MarketCandle.quality_state.in_(("VERIFIED", "RECONCILED")),
                MarketCandle.open_time >= earliest, MarketCandle.close_time <= end
            ).order_by(MarketCandle.open_time).limit(10001).all()
            if len(rows) > 10000:
                raise ValueError("Candle bound exceeded; narrow the requested period.")
            candles[symbol] = [SimpleNamespace(**dict(zip(columns, row))) for row in rows]
        db.rollback()  # Release the read transaction before doing replay CPU work.
    report = compare_records(records, candles)
    report.update(book=args.book, as_of_utc=end.isoformat(), selection="Latest entries per strategy/version, before coverage exclusions; open entries included",
                  venue="BINANCE", requested_per_strategy=args.per_strategy)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
