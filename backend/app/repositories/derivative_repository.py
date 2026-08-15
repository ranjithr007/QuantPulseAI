from sqlalchemy import true

from app.database.models.funding_rates import FundingRate
from app.database.models.futures_mark_prices import FuturesMarkPrice
from app.database.models.futures_margin_brackets import FuturesMarginBracket
from app.database.models.open_interest import OpenInterest
from app.repositories._db_utils import commit_or_rollback
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

    def save_funding(self, db, item):
        db.add(
            FundingRate(
                symbol=item["symbol"],
                rate=item["rate"],
                funding_time=item["time"],
            )
        )
        commit_or_rollback(db)

    def save_open_interest(self, db, item):
        db.add(
            OpenInterest(
                symbol=item["symbol"],
                value=item["value"],
                timestamp=item["time"],
            )
        )
        commit_or_rollback(db)

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
