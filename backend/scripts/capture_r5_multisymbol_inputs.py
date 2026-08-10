"""Capture point-in-time R5 inputs for the official futures symbol set."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.backtesting.frozen_replay_runner import capture_frozen_replay_context


DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT")


def capture_inputs(*, symbols, timeframe, limit, as_of, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    captured = {}
    missing = []
    for symbol in symbols:
        filename = f"{symbol}_{timeframe}_{as_of.strftime('%Y%m%dT%H%M%SZ')}.json"
        context, payload = capture_frozen_replay_context(
            symbol,
            timeframe,
            limit=limit,
            as_of_timestamp=as_of,
            output_path=output / filename,
        )
        candle_count = len(context.get("candles") or [])
        captured[symbol] = {
            "path": str(output / filename),
            "candle_count": candle_count,
            "stack_counts": {
                key: len(value or [])
                for key, value in (context.get("stack_candles") or {}).items()
            },
        }
        if candle_count < limit:
            missing.append(symbol)

    result = {
        "contract": "r5_multisymbol_input_capture_v1",
        "as_of": as_of.isoformat(),
        "timeframe": timeframe,
        "limit": int(limit),
        "symbols": list(symbols),
        "captured": captured,
        "missing_or_short": missing,
        "status": "READY" if not missing else "BLOCKED_INSUFFICIENT_INPUT_DATA",
    }
    report_path = output / f"multisymbol_capture_{as_of.strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if missing:
        raise RuntimeError(
            "Missing full frozen candle inputs for: " + ", ".join(missing)
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=12960)
    parser.add_argument("--output-dir", default="outputs/r5_frozen_inputs")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    args = parser.parse_args()
    capture_inputs(
        symbols=tuple(args.symbols),
        timeframe=args.timeframe,
        limit=args.limit,
        as_of=datetime.fromisoformat(args.as_of.replace("Z", "+00:00")),
        output_dir=args.output_dir,
    )
