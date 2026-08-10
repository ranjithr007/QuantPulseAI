"""Offline, fixed-input runner for proof-of-edge replay evidence."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.backtesting.trade_simulator import (
    _load_replay_stack_candles,
    execute_walk_forward,
)
from app.database.bootstrap import bootstrap_sqlite_demo_data
from app.database.sqlserver import SessionLocal
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.database.sqlserver import engine as db_engine
from app.repositories.candle_repository import get_candles_as_of
from app.repositories.derivative_repository import DerivativeRepository
from app.utils.freshness import normalize_timestamp_to_utc


CANDLE_FIELDS = (
    "symbol",
    "timeframe",
    "venue",
    "market_type",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "quote_volume",
    "quote_asset_volume",
    "candle_time",
    "open_time",
    "close_time",
    "is_final",
    "source",
    "revision",
    "quality_state",
)


def capture_frozen_replay_context(
    symbol,
    timeframe,
    *,
    limit,
    as_of_timestamp,
    output_path=None,
):
    """Capture all historical inputs once, optionally writing a JSON snapshot."""
    if isinstance(as_of_timestamp, str):
        as_of_timestamp = datetime.fromisoformat(as_of_timestamp.replace("Z", "+00:00"))
    as_of = normalize_timestamp_to_utc(as_of_timestamp)
    if as_of is None:
        raise ValueError("as_of_timestamp is required for a frozen replay")

    if USING_SQLITE_FALLBACK:
        bootstrap_sqlite_demo_data(db_engine)

    db = SessionLocal()
    try:
        candles = get_candles_as_of(db, symbol, timeframe, as_of, limit)
        stack_candles = _load_replay_stack_candles(
            db,
            symbol,
            timeframe,
            candles,
            limit,
            as_of_timestamp=as_of,
        )
        derivatives = DerivativeRepository().history_through(
            db,
            symbol,
            _latest_candle_timestamp(candles),
            mark_price_timeframe=timeframe,
        )
    finally:
        db.close()

    payload = {
        "contract": "r5_frozen_replay_input_v1",
        "captured_at": datetime.utcnow().isoformat() + "Z",
        "symbol": symbol,
        "timeframe": timeframe,
        "as_of": as_of.isoformat(),
        "limit": int(limit),
        "candles": [_serialize(candle) for candle in candles],
        "stack_candles": {
            key: [_serialize(candle) for candle in values]
            for key, values in stack_candles.items()
        },
        "derivative_history": {
            key: [_serialize(record) for record in values]
            for key, values in derivatives.items()
        },
    }
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return thaw_frozen_replay_context(payload), payload


def load_frozen_replay_context(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("contract") != "r5_frozen_replay_input_v1":
        raise ValueError("Unsupported frozen replay input contract")
    return thaw_frozen_replay_context(payload), payload


def thaw_frozen_replay_context(payload):
    return {
        "candles": [_thaw_candle(item) for item in payload.get("candles", [])],
        "stack_candles": {
            key: [_thaw_candle(item) for item in values]
            for key, values in (payload.get("stack_candles") or {}).items()
        },
        "derivative_history": {
            key: [_thaw_record(item) for item in values]
            for key, values in (payload.get("derivative_history") or {}).items()
        },
    }


def run_frozen_walk_forward(context, *, symbol, timeframe, signal, **options):
    """Run a walk-forward entirely from a thawed frozen context."""
    return execute_walk_forward(
        symbol,
        timeframe,
        signal,
        replay_context=context,
        **options,
    )


def _serialize(value):
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__table__"):
        return {
            field.name: _serialize(getattr(value, field.name, None))
            for field in value.__table__.columns
        }
    return value


def _thaw_candle(value):
    return SimpleNamespace(**_thaw_record(value))


def _thaw_record(value):
    thawed = {}
    for key, item in dict(value or {}).items():
        if isinstance(item, str) and (
            key.endswith("_time")
            or key in {"timestamp", "effective_at", "created_at", "updated_at"}
        ):
            try:
                item = datetime.fromisoformat(item.replace("Z", "+00:00"))
            except ValueError:
                pass
        thawed[key] = item
    return thawed


def _latest_candle_timestamp(candles):
    if not candles:
        return None
    candle = candles[-1]
    return getattr(candle, "close_time", None) or getattr(candle, "candle_time", None)
