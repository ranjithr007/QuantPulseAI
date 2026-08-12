"""Check candle-only readiness for the sealed directional-risk holdout.

This command deliberately reads only final-candle counts and timestamps. It
must not construct intelligence, signals, trades, or performance results.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.runtime import SessionLocal


HOLDOUT_START = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)
SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "DOGEUSDT",
)
REQUIRED_FINAL_CANDLES = {
    "1h": 2_880,
    "2h": 1_440,
    "4h": 720,
    "1d": 120,
}


def assess_readiness(rows, *, observed_at=None):
    observed = observed_at or datetime.now(timezone.utc)
    indexed = {
        (str(row["symbol"]), str(row["timeframe"])): row
        for row in rows
    }
    scopes = []
    for symbol in SYMBOLS:
        for timeframe, required in REQUIRED_FINAL_CANDLES.items():
            row = indexed.get((symbol, timeframe), {})
            available = int(row.get("final_candles") or 0)
            scopes.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "required_final_candles": required,
                    "available_final_candles": available,
                    "missing_final_candles": max(0, required - available),
                    "coverage_percent": round(
                        min(available / required, 1.0) * 100,
                        2,
                    ),
                    "first_close_time": _iso(row.get("first_close_time")),
                    "latest_close_time": _iso(row.get("latest_close_time")),
                    "status": "READY" if available >= required else "COLLECTING",
                }
            )
    ready = all(scope["status"] == "READY" for scope in scopes)
    return {
        "contract": "directional_risk_temporal_holdout_readiness_v1",
        "status": "READY_TO_OPEN" if ready else "COLLECTING_DATA",
        "outcome_data_accessed": False,
        "holdout_start_exclusive": HOLDOUT_START.isoformat(),
        "observed_at": _iso(observed),
        "symbols": list(SYMBOLS),
        "required_final_candles": REQUIRED_FINAL_CANDLES,
        "ready_scopes": sum(scope["status"] == "READY" for scope in scopes),
        "required_scopes": len(scopes),
        "scopes": scopes,
        "next_action": (
            "Run the preregistered holdout once; do not tune from its results."
            if ready
            else "Continue collecting final candles without evaluating holdout outcomes."
        ),
    }


def query_candle_inventory(session):
    statement = text(
        """
        SELECT COUNT(*) AS final_candles,
               MIN(close_time) AS first_close_time,
               MAX(close_time) AS latest_close_time
        FROM market_candles
        WHERE symbol = :symbol
          AND timeframe = :timeframe
          AND is_final = :is_final
          AND close_time > :holdout_start
        """
    )
    rows = []
    cutoff = HOLDOUT_START.replace(tzinfo=None)
    for symbol in SYMBOLS:
        for timeframe in REQUIRED_FINAL_CANDLES:
            result = session.execute(
                statement,
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "is_final": True,
                    "holdout_start": cutoff,
                },
            ).mappings().one()
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "final_candles": result["final_candles"],
                    "first_close_time": result["first_close_time"],
                    "latest_close_time": result["latest_close_time"],
                }
            )
    return rows


def _iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=(
            "outputs/directional_risk_confidence_calibration_20260812/"
            "holdout/readiness.json"
        ),
    )
    args = parser.parse_args()
    with SessionLocal() as session:
        payload = assess_readiness(query_candle_inventory(session))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

