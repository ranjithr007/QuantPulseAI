from datetime import timezone

from app.database.models.spot_market_candles import SpotMarketCandle
from app.repositories._db_utils import commit_or_rollback
from app.utils.freshness import normalize_timestamp_to_utc


class SpotMarketRepository:
    def save_many(self, db, items):
        items = list(items or [])
        if not items:
            return 0

        grouped = {}
        for raw in items:
            item = self._normalize(raw)
            key = (
                item["venue"],
                item["symbol"],
                item["timeframe"],
            )
            grouped.setdefault(key, {})[item["open_time"]] = item

        changed = 0
        for (venue, symbol, timeframe), by_open_time in grouped.items():
            existing_rows = (
                db.query(SpotMarketCandle)
                .filter(
                    SpotMarketCandle.venue == venue,
                    SpotMarketCandle.symbol == symbol,
                    SpotMarketCandle.timeframe == timeframe,
                    SpotMarketCandle.open_time.in_(list(by_open_time)),
                )
                .all()
            )
            existing = {row.open_time: row for row in existing_rows}
            for open_time, item in by_open_time.items():
                target = existing.get(open_time) or SpotMarketCandle()
                for field, value in item.items():
                    setattr(target, field, value)
                if open_time not in existing:
                    db.add(target)
                changed += 1
        commit_or_rollback(db)
        return changed

    def history_through(
        self,
        db,
        symbol,
        as_of_timestamp=None,
        *,
        timeframes=("1h", "2h", "4h", "1d"),
        limit_per_timeframe=5000,
    ):
        cutoff = normalize_timestamp_to_utc(as_of_timestamp)
        if cutoff is not None and cutoff.tzinfo is not None:
            cutoff = cutoff.astimezone(timezone.utc).replace(tzinfo=None)

        histories = {}
        for timeframe in timeframes:
            query = db.query(SpotMarketCandle).filter(
                SpotMarketCandle.symbol == str(symbol).upper(),
                SpotMarketCandle.timeframe == timeframe,
                SpotMarketCandle.is_final.is_(True),
            )
            if cutoff is not None:
                query = query.filter(SpotMarketCandle.close_time <= cutoff)
            rows = (
                query.order_by(
                    SpotMarketCandle.close_time.desc(),
                    SpotMarketCandle.id.desc(),
                )
                .limit(max(0, int(limit_per_timeframe)))
                .all()
            )
            histories[timeframe] = [self.serialize(row) for row in reversed(rows)]
        return histories

    @staticmethod
    def serialize(row):
        return {
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "open_time": row.open_time,
            "close_time": row.close_time,
            "open": row.open_price,
            "high": row.high_price,
            "low": row.low_price,
            "close": row.close_price,
            "base_volume": row.base_volume,
            "quote_volume": row.quote_volume,
            "trade_count": row.trade_count,
            "taker_buy_quote_volume": row.taker_buy_quote_volume,
            "taker_sell_quote_volume": row.taker_sell_quote_volume,
            "spot_delta_quote": row.spot_delta_quote,
            "is_final": row.is_final,
            "source": row.source,
        }

    @staticmethod
    def _normalize(item):
        return {
            "venue": str(item.get("venue") or "BINANCE").upper(),
            "market_type": "SPOT",
            "symbol": str(item["symbol"]).upper(),
            "timeframe": str(item["timeframe"]).lower(),
            "open_time": item["open_time"],
            "close_time": item["close_time"],
            "open_price": float(item.get("open", item.get("open_price"))),
            "high_price": float(item.get("high", item.get("high_price"))),
            "low_price": float(item.get("low", item.get("low_price"))),
            "close_price": float(item.get("close", item.get("close_price"))),
            "base_volume": float(item.get("base_volume") or 0.0),
            "quote_volume": float(item.get("quote_volume") or 0.0),
            "trade_count": int(item.get("trade_count") or 0),
            "taker_buy_quote_volume": float(item.get("taker_buy_quote_volume") or 0.0),
            "taker_sell_quote_volume": float(item.get("taker_sell_quote_volume") or 0.0),
            "spot_delta_quote": float(item.get("spot_delta_quote") or 0.0),
            "is_final": bool(item.get("is_final", True)),
            "source": str(item.get("source") or "BINANCE_SPOT_KLINE"),
        }
