from datetime import datetime
from datetime import timedelta
from datetime import timezone

from app.database.models.market_candles import MarketCandle
from app.repositories.candle_repository import get_latest_candle
from app.repositories._db_utils import commit_or_rollback
from app.utils.timeframes import candle_close_boundary_ms
from sqlalchemy import func
from sqlalchemy import true

FUTURE_CANDLE_TOLERANCE_SECONDS = 60


class MarketRepository:

    def save_candle(self, db, candle):
        return self.upsert_candle(db, candle) in {
            "INSERTED",
            "UPDATED",
            "FINALIZED",
        }

    def upsert_candle(self, db, candle, *, now=None, commit=True):
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        open_time = datetime.fromtimestamp(
            int(candle["open_time_ms"]) / 1000,
            timezone.utc,
        ).replace(tzinfo=None)
        open_time_utc = open_time.replace(tzinfo=timezone.utc)
        max_usable_time = now_utc + timedelta(
            seconds=FUTURE_CANDLE_TOLERANCE_SECONDS
        )
        if open_time_utc > max_usable_time or not _valid_ohlcv(candle):
            return "REJECTED"

        timeframe = str(candle["timeframe"])
        close_time_ms = candle.get("close_time_ms")
        if close_time_ms is None:
            close_time_ms = candle_close_boundary_ms(
                candle["open_time_ms"],
                timeframe,
            )
        close_time = datetime.fromtimestamp(
            int(close_time_ms) / 1000,
            timezone.utc,
        ).replace(tzinfo=None)
        incoming_final = bool(
            candle.get(
                "is_final",
                now_utc >= close_time.replace(tzinfo=timezone.utc),
            )
        )
        venue = str(candle.get("venue") or "UNKNOWN").upper()
        market_type = str(candle.get("market_type") or "FUTURES").upper()
        source = str(candle.get("source") or "UNKNOWN")

        existing = (
            db.query(MarketCandle)
            .filter(
                MarketCandle.symbol == candle["symbol"],
                MarketCandle.timeframe == timeframe,
                MarketCandle.venue == venue,
                MarketCandle.market_type == market_type,
                MarketCandle.open_time == open_time,
            )
            .first()
        )
        if existing:
            if bool(existing.is_final):
                return "UNCHANGED_FINAL"

            if not _candle_changed(
                existing,
                candle,
                close_time,
                incoming_final,
            ):
                return "UNCHANGED_PROVISIONAL"

            existing.open_price = candle["open"]
            existing.high_price = candle["high"]
            existing.low_price = candle["low"]
            existing.close_price = candle["close"]
            existing.volume = candle["volume"]
            existing.close_time = close_time
            existing.is_final = incoming_final
            existing.source = source
            existing.quality_state = (
                "VERIFIED" if incoming_final else "PROVISIONAL"
            )
            existing.revision = int(existing.revision or 0) + 1
            existing.updated_at = now_utc.replace(tzinfo=None)
            if commit:
                commit_or_rollback(db)
            return "FINALIZED" if incoming_final else "UPDATED"

        entity = MarketCandle(
            symbol=candle["symbol"],
            timeframe=timeframe,
            venue=venue,
            market_type=market_type,
            open_price=candle["open"],
            high_price=candle["high"],
            low_price=candle["low"],
            close_price=candle["close"],
            volume=candle["volume"],
            candle_time=open_time,
            open_time=open_time,
            close_time=close_time,
            is_final=incoming_final,
            source=source,
            ingested_at=now_utc.replace(tzinfo=None),
            updated_at=now_utc.replace(tzinfo=None),
            revision=1,
            quality_state="VERIFIED" if incoming_final else "PROVISIONAL",
        )
        db.add(entity)
        if commit:
            commit_or_rollback(db)
        return "INSERTED"

    def get_last_candle_time(self, db, symbol: str, timeframe: str):
        candle = get_latest_candle(db, symbol, timeframe)
        return candle.candle_time if candle else None

    def insert_final_candles_batch(self, db, candles, *, now=None):
        """Insert missing immutable historical candles with one query/commit per scope.

        The live upsert path remains authoritative for provisional refreshes. This
        batch path is deliberately insert-only and accepts finalized candles only,
        which makes large governed history backfills resumable and idempotent.
        """
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        prepared = {}
        rejected = 0
        for candle in candles or ():
            try:
                timeframe = str(candle["timeframe"])
                open_time_ms = int(candle["open_time_ms"])
                close_time_ms = int(
                    candle.get("close_time_ms")
                    or candle_close_boundary_ms(open_time_ms, timeframe)
                )
                open_time = datetime.fromtimestamp(
                    open_time_ms / 1000,
                    timezone.utc,
                ).replace(tzinfo=None)
                close_time = datetime.fromtimestamp(
                    close_time_ms / 1000,
                    timezone.utc,
                ).replace(tzinfo=None)
                venue = str(candle.get("venue") or "UNKNOWN").upper()
                market_type = str(
                    candle.get("market_type") or "FUTURES"
                ).upper()
                key = (
                    str(candle["symbol"]).upper(),
                    timeframe,
                    venue,
                    market_type,
                    open_time,
                )
            except (KeyError, TypeError, ValueError, OSError, OverflowError):
                rejected += 1
                continue

            if (
                not bool(candle.get("is_final"))
                or close_time.replace(tzinfo=timezone.utc) > now_utc
                or not _valid_ohlcv(candle)
            ):
                rejected += 1
                continue

            prepared[key] = (candle, close_time)

        inserted = 0
        existing_count = 0
        next_sqlite_id = _next_sqlite_candle_id(db)
        for scope, scoped_items in _group_prepared_candles(prepared).items():
            symbol, timeframe, venue, market_type = scope
            open_times = [key[-1] for key in scoped_items]
            existing_times = {
                value
                for (value,) in (
                    db.query(MarketCandle.open_time)
                    .filter(MarketCandle.symbol == symbol)
                    .filter(MarketCandle.timeframe == timeframe)
                    .filter(MarketCandle.venue == venue)
                    .filter(MarketCandle.market_type == market_type)
                    .filter(MarketCandle.open_time >= min(open_times))
                    .filter(MarketCandle.open_time <= max(open_times))
                    .all()
                )
            }
            entities = []
            for key, (candle, close_time) in scoped_items.items():
                open_time = key[-1]
                if open_time in existing_times:
                    existing_count += 1
                    continue
                entity = MarketCandle(
                    symbol=key[0],
                    timeframe=key[1],
                    venue=key[2],
                    market_type=key[3],
                    open_price=float(candle["open"]),
                    high_price=float(candle["high"]),
                    low_price=float(candle["low"]),
                    close_price=float(candle["close"]),
                    volume=float(candle["volume"]),
                    candle_time=open_time,
                    open_time=open_time,
                    close_time=close_time,
                    is_final=True,
                    source=str(candle.get("source") or "UNKNOWN"),
                    ingested_at=now_utc.replace(tzinfo=None),
                    updated_at=now_utc.replace(tzinfo=None),
                    revision=1,
                    quality_state="VERIFIED",
                )
                if next_sqlite_id is not None:
                    entity.id = next_sqlite_id
                    next_sqlite_id += 1
                entities.append(entity)
            if entities:
                db.add_all(entities)
                inserted += len(entities)

        if inserted:
            commit_or_rollback(db)
        return {
            "inserted": inserted,
            "existing": existing_count,
            "rejected": rejected,
        }

    def get_collection_cursor(
        self,
        db,
        symbol: str,
        timeframe: str,
        *,
        market_type="FUTURES",
    ):
        return (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol == symbol)
            .filter(MarketCandle.timeframe == timeframe)
            .filter(MarketCandle.market_type == market_type)
            .filter(MarketCandle.venue != "UNKNOWN")
            .order_by(
                MarketCandle.open_time.desc(),
                MarketCandle.id.desc(),
            )
            .first()
        )

    def get_source_candles(
        self,
        db,
        symbol: str,
        timeframe: str,
        venue: str,
        start_time,
        end_time,
    ):
        return (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol == symbol)
            .filter(MarketCandle.timeframe == timeframe)
            .filter(MarketCandle.market_type == "FUTURES")
            .filter(MarketCandle.venue == str(venue).upper())
            .filter(MarketCandle.is_final == true())
            .filter(MarketCandle.open_time >= start_time)
            .filter(MarketCandle.open_time <= end_time)
            .order_by(MarketCandle.open_time.asc())
            .all()
        )

    def delete_candles(self, db, symbol: str, timeframe: str):
        (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol == symbol)
            .filter(MarketCandle.timeframe == timeframe)
            .delete(synchronize_session=False)
        )
        commit_or_rollback(db)


def _valid_ohlcv(candle):
    try:
        open_price = float(candle["open"])
        high_price = float(candle["high"])
        low_price = float(candle["low"])
        close_price = float(candle["close"])
        volume = float(candle["volume"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        volume >= 0
        and high_price >= low_price
        and high_price >= max(open_price, close_price)
        and low_price <= min(open_price, close_price)
    )


def _group_prepared_candles(prepared):
    grouped = {}
    for key, value in prepared.items():
        grouped.setdefault(key[:4], {})[key] = value
    return grouped


def _next_sqlite_candle_id(db):
    dialect = getattr(getattr(getattr(db, "bind", None), "dialect", None), "name", None)
    if dialect != "sqlite":
        return None
    maximum = db.query(func.max(MarketCandle.id)).scalar() or 0
    return int(maximum) + 1


def _candle_changed(existing, candle, close_time, incoming_final):
    return any(
        (
            float(existing.open_price) != float(candle["open"]),
            float(existing.high_price) != float(candle["high"]),
            float(existing.low_price) != float(candle["low"]),
            float(existing.close_price) != float(candle["close"]),
            float(existing.volume) != float(candle["volume"]),
            existing.close_time != close_time,
            bool(existing.is_final) != bool(incoming_final),
        )
    )
