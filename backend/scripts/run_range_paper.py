"""Local isolated paper worker. Uses public GET endpoints only; no credentials."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.backtesting.spot_range_reversion import build_range_features
from app.paper_trading.range_experiment import SYMBOLS, initial_state, paper_cycle

BASE = "https://data-api.binance.vision"


def connect(directory):
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "paper.sqlite3", timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, kind TEXT, payload TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS candles (symbol TEXT, time INTEGER, payload TEXT, PRIMARY KEY(symbol,time))")
    db.commit()
    return db


def get(path, **params):
    if path not in ("/api/v3/klines", "/api/v3/depth", "/api/v3/exchangeInfo", "/api/v3/time"):
        raise ValueError("Only explicitly permitted public market endpoints are available")
    began = time.monotonic()
    with urlopen(BASE + path + "?" + urlencode(params), timeout=10) as response:
        body = json.loads(response.read())
    return body, time.monotonic() - began


def code_hash():
    paths = [Path(__file__), ROOT / "app/paper_trading/range_experiment.py",
             ROOT / "app/backtesting/spot_range_reversion.py",
             ROOT / "app/backtesting/spot_pullback_research.py",
             ROOT / "app/backtesting/spot_pullback_comparison.py",
             ROOT / "app/backtesting/spot_execution_probe.py"]
    return sha256(b"".join(p.read_bytes() for p in paths)).hexdigest()


def candles(db, symbol, now):
    cutoff = int(now.floor("15min").timestamp() * 1000)
    last = db.execute("SELECT MAX(time) FROM candles WHERE symbol=?", (symbol,)).fetchone()[0]
    first = int((now.floor("D") - pd.Timedelta(days=65)).timestamp() * 1000)
    cursor = last + 900000 if last is not None else first
    while cursor < cutoff:
        rows, _ = get("/api/v3/klines", symbol=symbol, interval="15m", startTime=cursor,
                      endTime=cutoff-1, limit=1000)
        if not rows:
            raise ValueError("Missing finalized candle coverage")
        final = [r for r in rows if r[0] + 900000 <= cutoff]
        if not final or final[-1][0] < cursor:
            raise ValueError("No new finalized candles")
        with db:
            db.executemany("INSERT OR IGNORE INTO candles VALUES (?,?,?)",
                           [(symbol, r[0], json.dumps(r)) for r in final])
        cursor = final[-1][0] + 900000
    rows = [json.loads(r[0]) for r in db.execute("SELECT payload FROM candles WHERE symbol=? ORDER BY time", (symbol,))]
    frame = pd.DataFrame([[float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[7])] for r in rows],
                         columns=["open","high","low","close","quote_volume"],
                         index=pd.to_datetime([r[0] for r in rows], unit="ms", utc=True))
    if frame.index[-1] + pd.Timedelta(minutes=15) != now.floor("15min"):
        raise ValueError("Stale candle tail")
    return frame


def serializable_row(row):
    result = {}
    for key, value in row.items():
        if pd.isna(value):
            continue
        result[key] = value.item() if hasattr(value, "item") else value
    return result


def status_file(directory, state):
    path = directory / "status.json"
    temporary = directory / "status.tmp"
    temporary.write_text(json.dumps(state, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def run(directory, once):
    # OS lock released on crash. Never delete another process's lock file.
    lock = (directory / "worker.lock").open("a+b")
    lock.seek(0)
    lock.write(b"1")
    lock.flush()
    lock.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    db = connect(directory)
    checksum = code_hash()
    now = pd.Timestamp.now(tz="UTC")
    with db:
        db.execute("INSERT OR IGNORE INTO account VALUES (1,?)", (json.dumps(initial_state(now, checksum)),))
    state = json.loads(db.execute("SELECT payload FROM account WHERE id=1").fetchone()[0])
    if state["code_hash"] != checksum:
        raise RuntimeError("Paper rules/code changed. Review the existing account; do not reset or silently migrate it.")
    cache, metadata, last_metadata = {}, {}, None
    (directory / "worker.pid").write_text(str(os.getpid()), encoding="ascii")
    print("Isolated range paper worker started; public market data only", flush=True)
    try:
        while not (directory / "STOP").exists():
            began = time.monotonic()
            now = pd.Timestamp.now(tz="UTC")
            errors, features, bars, books = [], {}, {}, {}
            try:
                server, duration = get("/api/v3/time")
                if duration > 3 or abs(server["serverTime"]/1000 - pd.Timestamp.now(tz="UTC").timestamp()) > 5:
                    raise ValueError("Clock/server freshness mismatch")
                if last_metadata is None or (now-last_metadata).total_seconds() >= 3600:
                    info, _ = get("/api/v3/exchangeInfo", symbols=json.dumps(list(SYMBOLS), separators=(",", ":")))
                    metadata = {s["symbol"]:s for s in info["symbols"]}
                    last_metadata = now
                for symbol in SYMBOLS:
                    if symbol not in cache or cache[symbol][0] != now.floor("15min"):
                        frame = candles(db, symbol, now)
                        feature_frame = build_range_features(frame)
                        feature = serializable_row(feature_frame.iloc[-1])
                        feature["available_at"] = feature_frame.index[-1].isoformat()
                        completed = [{"time":t.isoformat(), "end":(t+pd.Timedelta(minutes=15)).isoformat(),
                                      "open":r.open, "low":r.low, "high":r.high} for t,r in frame.tail(100).iterrows()]
                        cache[symbol] = (now.floor("15min"), feature, completed)
                    features[symbol], bars[symbol] = cache[symbol][1:]
            except Exception as exc:
                errors.append(type(exc).__name__ + ": " + str(exc))
                features = {}  # exits can still use fresh books when features fail
            for symbol in SYMBOLS:
                try:
                    book, duration = get("/api/v3/depth", symbol=symbol, limit=100)
                    books[symbol] = {"received_at":pd.Timestamp.now(tz="UTC").isoformat(),
                                     "latency_seconds":duration, "book":book}
                except Exception as exc:
                    errors.append(symbol + ": " + type(exc).__name__ + ": " + str(exc))
            now = pd.Timestamp.now(tz="UTC")
            with db:
                db.execute("BEGIN IMMEDIATE")
                state = json.loads(db.execute("SELECT payload FROM account WHERE id=1").fetchone()[0])
                if state["code_hash"] != checksum:
                    raise RuntimeError("Account policy hash mismatch")
                updated, events = paper_cycle(state, now, books, features, metadata, bars)
                updated["feed_errors"] = errors
                updated["worker_pid"] = os.getpid()
                if errors:
                    events.append({"time":now.isoformat(), "kind":"FEED_ERROR", "errors":errors})
                db.execute("UPDATE account SET payload=? WHERE id=1", (json.dumps(updated, allow_nan=False),))
                db.executemany("INSERT INTO events(time,kind,payload) VALUES (?,?,?)",
                               [(e["time"], e["kind"], json.dumps(e, allow_nan=False)) for e in events])
            status_file(directory, updated)
            print(json.dumps({"time":updated["last_cycle"], "equity":updated["equity"],
                              "positions":len(updated["positions"]), "healthy":updated["data_healthy"],
                              "halt":updated["halt"], "events":[e["kind"] for e in events]}), flush=True)
            if once:
                break
            time.sleep(max(1, 15-(time.monotonic()-began)))
    finally:
        db.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "status", "pause", "stop"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    if args.command == "run":
        run(args.directory, args.once)
    elif args.command == "stop":
        (args.directory / "STOP").write_text("Operator requested stop; open simulations require reconciliation before restart.")
    else:
        db = connect(args.directory)
        with db:
            row = db.execute("SELECT payload FROM account WHERE id=1").fetchone()
            if row is None:
                raise RuntimeError("Paper account has not started")
            state = json.loads(row[0])
            if args.command == "pause":
                state["manual_pause"] = True
                db.execute("UPDATE account SET payload=? WHERE id=1", (json.dumps(state),))
        print(json.dumps(state, indent=2), flush=True)
        db.close()


if __name__ == "__main__":
    main()
