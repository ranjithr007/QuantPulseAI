from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import func, true

from app.database.models.market_candles import MarketCandle
from app.utils.freshness import normalize_timestamp_to_utc


FUTURE_CANDLE_TOLERANCE_SECONDS = 60
MIN_CANONICAL_CANDLE_CANDIDATES = 32


def _normalized_candle_time(candle):
    candle_time = (
        getattr(candle, "open_time", None)
        or getattr(candle, "candle_time", None)
    )
    normalized = normalize_timestamp_to_utc(candle_time)
    if normalized is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return normalized


def _normalized_close_time(candle):
    normalized = normalize_timestamp_to_utc(
        getattr(candle, "close_time", None)
    )
    if normalized is not None:
        return normalized
    return _normalized_candle_time(candle)


def _canonical_rank(candle):
    quality_state = str(
        getattr(candle, "quality_state", "") or ""
    ).upper()
    venue = str(getattr(candle, "venue", "") or "").upper()
    quality_rank = {
        "RECONCILED": 4,
        "VERIFIED": 3,
        "LEGACY_UNVERIFIED": 1,
    }.get(quality_state, 0)
    return (
        quality_rank,
        int(venue not in {"", "UNKNOWN"}),
        int(getattr(candle, "revision", 0) or 0),
        int(getattr(candle, "id", 0) or 0),
    )


def _is_final_and_closed(candle, cutoff):
    return (
        getattr(candle, "is_final", True) is not False
        and _normalized_close_time(candle) <= cutoff
    )


def _deduplicate_and_order(candles, limit):
    best_by_open_time = {}
    for candle in candles:
        identity_time = _normalized_candle_time(candle)
        identity_key = (
            identity_time,
            (
                int(getattr(candle, "id", 0) or id(candle))
                if identity_time == datetime.min.replace(tzinfo=timezone.utc)
                else 0
            ),
        )
        existing = best_by_open_time.get(identity_key)
        if existing is None or _canonical_rank(candle) > _canonical_rank(existing):
            best_by_open_time[identity_key] = candle

    ordered = [
        best_by_open_time[key]
        for key in sorted(best_by_open_time)
    ]
    return ordered[-limit:]


def get_final_candle_series(db, symbol, timeframe, limit=200):
    """Return one immutable, final candle per open time in ascending order.

    During the R1 transition, verified venue-specific rows take precedence
    over overlapping legacy rows. A candle is usable only after its close
    boundary and when ``is_final`` is true.
    """

    candidate_limit = max(limit * 4, MIN_CANONICAL_CANDLE_CANDIDATES)
    cache = _session_cache(db, "quantpulse_final_candle_series")
    cache_key = (symbol, timeframe, candidate_limit)

    cached_series = _cached_candle_series(
        cache,
        symbol,
        timeframe,
        candidate_limit,
    )
    if cached_series is not None:
        return cached_series[-limit:]

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    raw_time_candidates = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .filter(MarketCandle.is_final == true())
        .filter(MarketCandle.close_time <= now)
        .order_by(MarketCandle.candle_time.desc())
        .limit(candidate_limit)
        .all()
    )
    recent_insert_candidates = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .filter(MarketCandle.is_final == true())
        .filter(MarketCandle.close_time <= now)
        .order_by(MarketCandle.id.desc())
        .limit(candidate_limit)
        .all()
    )
    candidates = {
        getattr(candle, "id", id(candle)): candle
        for candle in raw_time_candidates + recent_insert_candidates
    }.values()
    max_usable_time = datetime.now(timezone.utc) + timedelta(
        seconds=FUTURE_CANDLE_TOLERANCE_SECONDS
    )
    usable_candidates = [
        candle
        for candle in candidates
        if (
            _is_final_and_closed(candle, max_usable_time)
            and _normalized_candle_time(candle) <= max_usable_time
        )
    ]

    ordered_candidates = _deduplicate_and_order(
        usable_candidates,
        candidate_limit,
    )
    if cache is not None:
        cache[cache_key] = ordered_candidates

    return ordered_candidates[-limit:]


def get_latest_candles(db, symbol, timeframe, limit=200):
    """Compatibility name for the canonical ascending final-candle contract."""
    return get_final_candle_series(db, symbol, timeframe, limit)


def get_latest_candle(db, symbol, timeframe):
    candles = get_latest_candles(db, symbol, timeframe, limit=1)

    return candles[-1] if candles else None


def prime_latest_candle_cache(db, symbols, timeframe):
    """Load the latest canonical candle candidates for many symbols in two queries."""
    cache = _session_cache(db, "quantpulse_final_candle_series")
    normalized = sorted({str(symbol).strip().upper() for symbol in symbols or [] if symbol})
    if cache is None or not normalized:
        return

    candidate_limit = MIN_CANONICAL_CANDLE_CANDIDATES
    missing = [
        symbol
        for symbol in normalized
        if _cached_candle_series(cache, symbol, timeframe, candidate_limit) is None
    ]
    if not missing:
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    common_filters = (
        MarketCandle.symbol.in_(missing),
        MarketCandle.timeframe == timeframe,
        MarketCandle.is_final == true(),
        MarketCandle.close_time <= now,
    )
    ranked_by_time = (
        db.query(
            MarketCandle.id.label("market_candle_id"),
            func.row_number()
            .over(
                partition_by=MarketCandle.symbol,
                order_by=MarketCandle.candle_time.desc(),
            )
            .label("row_number"),
        )
        .filter(*common_filters)
        .subquery()
    )
    ranked_by_insert = (
        db.query(
            MarketCandle.id.label("market_candle_id"),
            func.row_number()
            .over(
                partition_by=MarketCandle.symbol,
                order_by=MarketCandle.id.desc(),
            )
            .label("row_number"),
        )
        .filter(*common_filters)
        .subquery()
    )

    candidates = {}
    for ranked in (ranked_by_time, ranked_by_insert):
        rows = (
            db.query(MarketCandle)
            .join(ranked, MarketCandle.id == ranked.c.market_candle_id)
            .filter(ranked.c.row_number <= candidate_limit)
            .all()
        )
        for candle in rows:
            candidates[getattr(candle, "id", id(candle))] = candle

    cutoff = datetime.now(timezone.utc) + timedelta(
        seconds=FUTURE_CANDLE_TOLERANCE_SECONDS
    )
    by_symbol = {symbol: [] for symbol in missing}
    for candle in candidates.values():
        if (
            _is_final_and_closed(candle, cutoff)
            and _normalized_candle_time(candle) <= cutoff
        ):
            by_symbol.setdefault(candle.symbol, []).append(candle)

    for symbol in missing:
        cache[(symbol, timeframe, candidate_limit)] = _deduplicate_and_order(
            by_symbol.get(symbol, []),
            candidate_limit,
        )


def get_final_candles_after(db, symbol, timeframe, after_timestamp, limit=1000):
    """Return the earliest canonical final candles after a durable checkpoint."""

    after = normalize_timestamp_to_utc(after_timestamp)
    if after is None:
        return get_final_candle_series(db, symbol, timeframe, limit=limit)
    if after.tzinfo is not None:
        after = after.astimezone(timezone.utc).replace(tzinfo=None)

    requested_limit = max(1, int(limit))
    candidate_limit = max(requested_limit * 4, 500)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    candidates = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .filter(MarketCandle.is_final == true())
        .filter(MarketCandle.open_time > after)
        .filter(MarketCandle.close_time <= now)
        .order_by(MarketCandle.open_time.asc(), MarketCandle.id.asc())
        .limit(candidate_limit)
        .all()
    )
    cutoff = now.replace(tzinfo=timezone.utc)
    usable = [
        candle
        for candle in candidates
        if _is_final_and_closed(candle, cutoff)
    ]
    ordered = _deduplicate_and_order(usable, candidate_limit)
    return ordered[:requested_limit]


def get_candles_as_of(db, symbol, timeframe, as_of_timestamp, limit=200):
    as_of = normalize_timestamp_to_utc(as_of_timestamp)
    if as_of is None:
        return []

    if as_of.tzinfo is not None:
        as_of = as_of.astimezone(timezone.utc).replace(tzinfo=None)

    # Canonical identity is unique per venue/market/symbol/timeframe/open_time;
    # the active futures sources contribute at most one row per venue. Two
    # rows per candle therefore provide revision/venue headroom without asking
    # SQL Server to sort an unnecessarily large 4x history window.
    candidate_limit = max(limit * 2, 500)
    candidates = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .filter(MarketCandle.is_final == true())
        # Use the indexed candle-time range for the historical seek. The
        # close-time predicate remains below as the authoritative forming-bar
        # guard because it is not part of the canonical composite index.
        .filter(MarketCandle.candle_time <= as_of)
        .filter(MarketCandle.close_time <= as_of)
        .order_by(MarketCandle.candle_time.desc())
        .limit(candidate_limit)
        .all()
    )

    cutoff = as_of.replace(tzinfo=timezone.utc)
    usable_candidates = [
        candle
        for candle in candidates
        if _is_final_and_closed(candle, cutoff)
    ]
    return _deduplicate_and_order(usable_candidates, limit)


def _session_cache(db, key):
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return None

    return info.setdefault(key, {})


def _cached_candle_series(cache, symbol, timeframe, candidate_limit):
    if cache is None:
        return None

    exact = cache.get((symbol, timeframe, candidate_limit))
    if exact is not None:
        return exact

    reusable = [
        (cached_limit, records)
        for (cached_symbol, cached_timeframe, cached_limit), records in cache.items()
        if (
            cached_symbol == symbol
            and cached_timeframe == timeframe
            and cached_limit >= candidate_limit
        )
    ]
    if not reusable:
        return None

    return min(reusable, key=lambda item: item[0])[1]
