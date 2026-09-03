from datetime import timedelta

from sqlalchemy import and_, func, true

from app.database.models.funding_rates import FundingRate
from app.database.models.futures_mark_prices import FuturesMarkPrice
from app.database.models.futures_margin_brackets import FuturesMarginBracket
from app.database.models.open_interest import OpenInterest
from app.repositories._db_utils import commit_or_rollback
from app.utils.freshness import normalize_timestamp_to_naive_utc
from app.utils.freshness import normalize_timestamp_to_utc


class DerivativeRepository:
    def latest_mark_price(self, db, symbol, timeframe="5m"):
        return (
            db.query(FuturesMarkPrice)
            .filter(
                FuturesMarkPrice.symbol == str(symbol).upper(),
                FuturesMarkPrice.timeframe == timeframe,
                FuturesMarkPrice.is_final == true(),
            )
            .order_by(
                FuturesMarkPrice.close_time.desc(),
                FuturesMarkPrice.id.desc(),
            )
            .first()
        )

    def latest_mark_prices(self, db, symbols, timeframe="5m"):
        """Load the latest final mark for every requested symbol in one query."""

        normalized_symbols = sorted(
            {
                str(symbol).strip().upper()
                for symbol in (symbols or ())
                if str(symbol).strip()
            }
        )
        if not normalized_symbols:
            return {}

        latest_times = (
            db.query(
                FuturesMarkPrice.symbol.label("symbol"),
                func.max(FuturesMarkPrice.close_time).label("close_time"),
            )
            .filter(
                FuturesMarkPrice.symbol.in_(normalized_symbols),
                FuturesMarkPrice.timeframe == timeframe,
                FuturesMarkPrice.is_final == true(),
            )
            .group_by(FuturesMarkPrice.symbol)
            .subquery()
        )
        rows = (
            db.query(FuturesMarkPrice)
            .join(
                latest_times,
                and_(
                    FuturesMarkPrice.symbol == latest_times.c.symbol,
                    FuturesMarkPrice.close_time == latest_times.c.close_time,
                ),
            )
            .filter(
                FuturesMarkPrice.timeframe == timeframe,
                FuturesMarkPrice.is_final == true(),
            )
            .order_by(FuturesMarkPrice.symbol.asc(), FuturesMarkPrice.id.desc())
            .all()
        )
        latest_by_symbol = {}
        for row in rows:
            latest_by_symbol.setdefault(str(row.symbol).upper(), row)
        return latest_by_symbol

    def save_funding(self, db, item):
        symbol = str(item["symbol"]).upper()
        existing = (
            db.query(FundingRate)
            .filter(
                FundingRate.symbol == symbol,
                FundingRate.funding_time == item["time"],
            )
            .first()
        )
        if existing is not None:
            existing.rate = item["rate"]
            commit_or_rollback(db)
            return existing

        record = FundingRate(
            symbol=symbol,
            rate=item["rate"],
            funding_time=item["time"],
        )
        db.add(record)
        commit_or_rollback(db)
        return record

    def save_open_interest(self, db, item):
        symbol = str(item["symbol"]).upper()
        timestamp = normalize_timestamp_to_naive_utc(item["time"])
        bucket_start = timestamp.replace(
            minute=(timestamp.minute // 2) * 2,
            second=0,
            microsecond=0,
        )
        bucket_end = bucket_start + timedelta(minutes=2)
        existing = (
            db.query(OpenInterest)
            .filter(
                OpenInterest.symbol == symbol,
                OpenInterest.timestamp >= bucket_start,
                OpenInterest.timestamp < bucket_end,
            )
            .order_by(OpenInterest.timestamp.asc(), OpenInterest.id.asc())
            .first()
        )
        if existing is not None:
            # Preserve the first observation in the bucket. Updating it with a
            # later value would rewrite historical evidence used by backtests.
            return existing

        record = OpenInterest(
            symbol=symbol,
            value=item["value"],
            timestamp=timestamp,
        )
        db.add(record)
        commit_or_rollback(db)
        return record

    def save_mark_prices(self, db, items):
        items = list(items or [])
        if not items:
            return

        # A collector batch contains 1h, 4h, and 1d rows. Query each complete
        # identity group independently; using the first row's timeframe for the
        # whole batch misses existing higher-timeframe rows and violates the
        # database unique key on every subsequent collection cycle.
        grouped = {}
        for item in items:
            group_key = (
                item["venue"],
                item["market_type"],
                item["symbol"],
                item["timeframe"],
            )
            grouped.setdefault(group_key, {})[item["open_time"]] = item

        for (venue, market_type, symbol, timeframe), items_by_open_time in grouped.items():
            existing_rows = (
                db.query(FuturesMarkPrice)
                .filter(
                    FuturesMarkPrice.venue == venue,
                    FuturesMarkPrice.market_type == market_type,
                    FuturesMarkPrice.symbol == symbol,
                    FuturesMarkPrice.timeframe == timeframe,
                    FuturesMarkPrice.open_time.in_(list(items_by_open_time)),
                )
                .all()
            )
            existing_by_open_time = {
                row.open_time: row
                for row in existing_rows
            }
            for open_time, item in items_by_open_time.items():
                existing = existing_by_open_time.get(open_time)
                target = existing or FuturesMarkPrice()
                for field in (
                    "venue",
                    "market_type",
                    "symbol",
                    "timeframe",
                    "open_time",
                    "close_time",
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                    "is_final",
                    "source",
                ):
                    setattr(target, field, item[field])
                if existing is None:
                    db.add(target)
        commit_or_rollback(db)

    def save_margin_brackets(self, db, items):
        for item in items or []:
            exists = (
                db.query(FuturesMarginBracket.id)
                .filter(
                    FuturesMarginBracket.venue == item["venue"],
                    FuturesMarginBracket.symbol == item["symbol"],
                    FuturesMarginBracket.snapshot_version
                    == item["snapshot_version"],
                    FuturesMarginBracket.bracket_number
                    == item["bracket_number"],
                )
                .first()
            )
            if exists:
                continue
            db.add(FuturesMarginBracket(**item))
        commit_or_rollback(db)

    def history_through(
        self,
        db,
        symbol,
        as_of_timestamp=None,
        limit=5000,
        mark_price_timeframe="1h",
    ):
        cutoff = normalize_timestamp_to_utc(as_of_timestamp)
        if cutoff is not None and cutoff.tzinfo is not None:
            cutoff = cutoff.replace(tzinfo=None)

        funding_query = db.query(FundingRate).filter(FundingRate.symbol == symbol)
        oi_query = db.query(OpenInterest).filter(OpenInterest.symbol == symbol)
        mark_query = db.query(FuturesMarkPrice).filter(
            FuturesMarkPrice.symbol == symbol,
            FuturesMarkPrice.timeframe == mark_price_timeframe,
            FuturesMarkPrice.is_final == true(),
        )
        bracket_query = db.query(FuturesMarginBracket).filter(
            FuturesMarginBracket.symbol == symbol,
        )
        if cutoff is not None:
            funding_query = funding_query.filter(FundingRate.funding_time <= cutoff)
            oi_query = oi_query.filter(OpenInterest.timestamp <= cutoff)
            mark_query = mark_query.filter(FuturesMarkPrice.close_time <= cutoff)
            bracket_query = bracket_query.filter(
                FuturesMarginBracket.effective_at <= cutoff
            )

        funding = (
            funding_query
            .order_by(FundingRate.funding_time.desc(), FundingRate.id.desc())
            .limit(limit)
            .all()
        )
        open_interest = (
            oi_query
            .order_by(OpenInterest.timestamp.desc(), OpenInterest.id.desc())
            .limit(limit)
            .all()
        )
        mark_prices = (
            mark_query
            .order_by(FuturesMarkPrice.close_time.desc(), FuturesMarkPrice.id.desc())
            .limit(limit)
            .all()
        )
        margin_brackets = (
            bracket_query
            .order_by(
                FuturesMarginBracket.effective_at.desc(),
                FuturesMarginBracket.id.desc(),
            )
            .limit(limit)
            .all()
        )
        return {
            "funding": list(reversed(funding)),
            "open_interest": list(reversed(open_interest)),
            "mark_prices": list(reversed(mark_prices)),
            "margin_brackets": list(reversed(margin_brackets)),
        }
