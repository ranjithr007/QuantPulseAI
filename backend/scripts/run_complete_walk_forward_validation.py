"""Run the complete governed walk-forward matrix and write consolidated evidence.

The runner evaluates both LONG and SHORT for every symbol/timeframe scope.  It
builds the expensive point-in-time intelligence timelines once per symbol and
reuses them across all timeframe and direction runs.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func

from app.api.v1.backtest_api import _load_paper_measurement
from app.api.v1.backtest_api import _resolve_walk_forward_configuration
from app.backtesting.phase2_validation_artifacts import (
    persist_phase2_validation_artifact,
)
from app.backtesting.phase2_validation_report import build_phase2_validation_report
from app.backtesting.trade_simulator import (
    _build_in_memory_stack_resolver,
    _latest_candle_timestamp,
    _stack_history_limit,
    execute_walk_forward,
)
from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.repositories.candle_repository import get_candles_as_of
from app.repositories.derivative_repository import DerivativeRepository
from app.paper_trading.exit_policy import PAPER_MAX_HOLD_HOURS
from app.paper_trading.exit_policy import PAPER_STAGED_EXIT_POLICY
from app.paper_trading.exit_policy import PAPER_STOP_LOSS_PERCENT
from app.paper_trading.exit_policy import PAPER_TARGET1_FRACTION
from app.paper_trading.exit_policy import PAPER_TARGET1_PERCENT
from app.paper_trading.exit_policy import PAPER_TARGET2_PERCENT


RUN_VERSION = "complete_walk_forward_validation_v4_staged_exit_parity"
PRODUCTION_MAX_RISK_PERCENT = 1.0
PRODUCTION_STOP_PERCENT = PAPER_STOP_LOSS_PERCENT
PRODUCTION_TARGET_PERCENT = PAPER_TARGET1_PERCENT
DEFAULT_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "DOGEUSDT",
)
DEFAULT_TIMEFRAMES = tuple(OFFICIAL_ENTRY_TIMEFRAMES)
DEFAULT_SIGNALS = ("LONG", "SHORT")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--signals", default=",".join(DEFAULT_SIGNALS))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--as-of")
    parser.add_argument("--run-id")
    arguments = parser.parse_args()

    symbols = _csv(arguments.symbols, upper=True)
    timeframes = _csv(arguments.timeframes)
    signals = _csv(arguments.signals, upper=True)
    _validate_scope(symbols, timeframes, signals)
    as_of = _parse_as_of(arguments.as_of) or _latest_hourly_common_cutoff(symbols)
    started_at = datetime.now(timezone.utc)
    run_id = arguments.run_id or started_at.strftime("%Y%m%d_%H%M%S")
    run_dir = _outputs_root() / f"complete_walk_forward_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    worker_arguments = [
        {
            "symbol": symbol,
            "timeframes": timeframes,
            "signals": signals,
            "as_of": as_of.isoformat(),
            "run_at": started_at.isoformat(),
            "run_dir": str(run_dir),
        }
        for symbol in symbols
    ]
    results = []
    worker_count = max(1, min(int(arguments.workers), len(symbols)))
    print(
        f"{RUN_VERSION} starting: symbols={len(symbols)} "
        f"scopes={len(symbols) * len(timeframes)} side_runs="
        f"{len(symbols) * len(timeframes) * len(signals)} workers={worker_count} "
        f"as_of={as_of.isoformat()}",
        flush=True,
    )

    if worker_count == 1:
        for item in worker_arguments:
            results.append(_run_symbol(item))
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_run_symbol, item): item["symbol"]
                for item in worker_arguments
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - process boundary
                    result = {
                        "symbol": symbol,
                        "status": "FAILED",
                        "error": str(exc),
                        "records": [],
                    }
                results.append(result)
                print(
                    f"[{symbol}] worker {result.get('status')} "
                    f"records={len(result.get('records') or [])}",
                    flush=True,
                )

    payload = _consolidated_payload(
        results,
        symbols=symbols,
        timeframes=timeframes,
        signals=signals,
        as_of=as_of,
        started_at=started_at,
    )
    json_path = run_dir / "consolidated_walk_forward_report.json"
    markdown_path = run_dir / "consolidated_walk_forward_report.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "completed_side_runs": payload["summary"]["completed_side_runs"],
                "failed_side_runs": payload["summary"]["failed_side_runs"],
                "json_path": str(json_path.resolve()),
                "markdown_path": str(markdown_path.resolve()),
            },
            indent=2,
        ),
        flush=True,
    )


def _run_symbol(arguments):
    symbol = arguments["symbol"]
    timeframes = tuple(arguments["timeframes"])
    signals = tuple(arguments["signals"])
    as_of = _parse_as_of(arguments["as_of"])
    run_at = _parse_as_of(arguments["run_at"])
    run_dir = Path(arguments["run_dir"])
    checkpoint_path = run_dir / f"{symbol}.json"
    checkpoint = _load_checkpoint(checkpoint_path, symbol)
    completed_keys = {
        (item.get("timeframe"), item.get("signal"))
        for item in checkpoint["records"]
        if item.get("status") == "COMPLETED"
    }
    pending = [
        (timeframe, signal)
        for timeframe in timeframes
        for signal in signals
        if (timeframe, signal) not in completed_keys
    ]
    if not pending:
        checkpoint["status"] = "COMPLETED"
        checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_checkpoint(checkpoint_path, checkpoint)
        return checkpoint

    print(f"[{symbol}] loading frozen canonical history", flush=True)
    started = time.perf_counter()
    configurations = {
        timeframe: _resolve_walk_forward_configuration(
            timeframe,
            None,
            None,
            None,
            None,
        )
        for timeframe in timeframes
    }
    stack_candles, derivative_history = _load_symbol_history(
        symbol,
        timeframes,
        configurations,
        as_of,
    )
    first_timeframe = timeframes[0]
    first_resolver = _build_in_memory_stack_resolver(
        symbol,
        stack_candles,
        derivative_history=derivative_history,
        feature_timeframe=first_timeframe,
    )
    timelines = first_resolver.stateful_timelines
    stack_cache = first_resolver.stack_cache
    resolvers = {first_timeframe: first_resolver}
    print(
        f"[{symbol}] intelligence timelines ready in "
        f"{time.perf_counter() - started:.1f}s",
        flush=True,
    )
    paper_measurement = _load_paper_measurement(symbol)

    for timeframe, signal in pending:
        scope_started = time.perf_counter()
        config = configurations[timeframe]
        resolver = resolvers.get(timeframe)
        if resolver is None:
            resolver = _build_in_memory_stack_resolver(
                symbol,
                stack_candles,
                derivative_history=derivative_history,
                feature_timeframe=timeframe,
                stateful_timelines=timelines,
                stack_cache=stack_cache,
            )
            resolvers[timeframe] = resolver
        selected_candles = list(stack_candles[timeframe])[-config["limit"] :]
        replay_context = {
            "candles": selected_candles,
            "stack_candles": stack_candles,
            "derivative_history": derivative_history,
            "_runtime": {
                "candles": selected_candles,
                "derivative_history": derivative_history,
                "stack_resolver": resolver,
                "feature_resolver": resolver.feature_resolver,
            },
        }
        try:
            result = execute_walk_forward(
                symbol,
                timeframe,
                signal,
                stop_grid=(PRODUCTION_STOP_PERCENT,),
                target_grid=(PRODUCTION_TARGET_PERCENT,),
                exit_distance_model="PAPER_POLICY",
                limit=config["limit"],
                train_size=config["train_size"],
                test_size=config["test_size"],
                step_size=config["step_size"],
                mode="EXPANDING",
                strategy="SIGNAL_GATED",
                risk_percent_per_trade=PRODUCTION_MAX_RISK_PERCENT,
                as_of_timestamp=as_of,
                replay_context=replay_context,
            )
            report = build_phase2_validation_report(
                result,
                symbol=symbol,
                timeframe=timeframe,
                signal=signal,
                as_of=run_at,
                paper_measurement=paper_measurement,
            )
            artifact = persist_phase2_validation_artifact(
                report,
                result,
                symbol=symbol,
                timeframe=timeframe,
                signal=signal,
                as_of=run_at,
            )
            record = _scope_record(
                symbol,
                timeframe,
                signal,
                result,
                report,
                artifact,
                time.perf_counter() - scope_started,
            )
        except Exception as exc:
            record = {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": signal,
                "status": "FAILED",
                "error": str(exc),
                "elapsed_seconds": round(time.perf_counter() - scope_started, 3),
            }
        checkpoint["records"] = [
            item
            for item in checkpoint["records"]
            if (item.get("timeframe"), item.get("signal")) != (timeframe, signal)
        ] + [record]
        checkpoint["status"] = "RUNNING"
        checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_checkpoint(checkpoint_path, checkpoint)
        print(
            f"[{symbol} {timeframe} {signal}] {record['status']} "
            f"folds={record.get('fold_count')} trades={record.get('oos_total_trades')} "
            f"elapsed={record['elapsed_seconds']}s",
            flush=True,
        )

    checkpoint["status"] = (
        "COMPLETED"
        if len(checkpoint["records"]) == len(timeframes) * len(signals)
        and all(item.get("status") == "COMPLETED" for item in checkpoint["records"])
        else "PARTIAL"
    )
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_checkpoint(checkpoint_path, checkpoint)
    return checkpoint


def _load_symbol_history(symbol, timeframes, configurations, as_of):
    required_limits = {
        target: max(
            _stack_history_limit(selected, target, configurations[selected]["limit"])
            for selected in timeframes
        )
        for target in DEFAULT_TIMEFRAMES
    }
    db = SessionLocal()
    try:
        stack = {
            timeframe: get_candles_as_of(
                db,
                symbol,
                timeframe,
                as_of,
                required_limits[timeframe],
            )
            for timeframe in DEFAULT_TIMEFRAMES
        }
        for timeframe in timeframes:
            required = configurations[timeframe]["limit"]
            if len(stack[timeframe]) < required:
                raise ValueError(
                    f"{symbol} {timeframe} has {len(stack[timeframe])} candles; "
                    f"{required} are required"
                )
        latest = max(
            (_latest_candle_timestamp(records) for records in stack.values() if records),
            default=None,
        )
        derivatives = DerivativeRepository().history_through(
            db,
            symbol,
            latest,
            mark_price_timeframe="1h",
        )
        return stack, derivatives
    finally:
        db.close()


def _scope_record(symbol, timeframe, signal, result, report, artifact, elapsed):
    metrics = dict(report.get("derived_metrics") or {})
    contract = dict(result.get("validation_contract") or {})
    gate = dict(report.get("architecture_gate") or {})
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": signal,
        "status": "COMPLETED",
        "validation_status": result.get("validation_status"),
        "contract_status": contract.get("contract_status"),
        "fold_count": int(result.get("fold_count") or 0),
        "architecture_gate_status": gate.get("status"),
        "overall_status": report.get("overall_status"),
        "evidence_status": report.get("evidence_status"),
        "promotion_allowed": False,
        "oos_total_trades": metrics.get("out_of_sample_total_trades"),
        "oos_total_return_percent": metrics.get("out_of_sample_total_return_percent"),
        "oos_profit_factor": metrics.get("out_of_sample_profit_factor"),
        "oos_win_rate": metrics.get("out_of_sample_win_rate"),
        "oos_max_drawdown_percent": metrics.get("out_of_sample_max_drawdown_percent"),
        "oos_payoff_ratio": metrics.get("out_of_sample_payoff_ratio"),
        "oos_annualized_sharpe": metrics.get("out_of_sample_annualized_sharpe"),
        "blocked_by": list(report.get("blocked_by") or []),
        "next_action": report.get("next_action"),
        "artifact": artifact,
        "elapsed_seconds": round(elapsed, 3),
    }


def _consolidated_payload(results, *, symbols, timeframes, signals, as_of, started_at):
    records = sorted(
        [record for result in results for record in (result.get("records") or [])],
        key=lambda item: (
            symbols.index(item.get("symbol")) if item.get("symbol") in symbols else 999,
            timeframes.index(item.get("timeframe")) if item.get("timeframe") in timeframes else 999,
            signals.index(item.get("signal")) if item.get("signal") in signals else 999,
        ),
    )
    expected_side_runs = len(symbols) * len(timeframes) * len(signals)
    completed = sum(1 for item in records if item.get("status") == "COMPLETED")
    failed = expected_side_runs - completed
    contract_passes = sum(1 for item in records if item.get("contract_status") == "PASS")
    architecture_passes = sum(
        1 for item in records if item.get("architecture_gate_status") == "PASS"
    )
    artifact_starts = [
        _parse_as_of((item.get("artifact") or {}).get("saved_at"))
        for item in records
        if (item.get("artifact") or {}).get("saved_at")
    ]
    effective_started_at = min(artifact_starts or [started_at])
    finished_at = datetime.now(timezone.utc)
    return {
        "source": RUN_VERSION,
        "status": "COMPLETED" if failed == 0 else "PARTIAL",
        "started_at": effective_started_at.isoformat(),
        "completed_at": finished_at.isoformat(),
        "elapsed_seconds": round(
            (finished_at - effective_started_at).total_seconds(),
            3,
        ),
        "as_of": as_of.isoformat(),
        "scope": {
            "symbols": list(symbols),
            "timeframes": list(timeframes),
            "signals": list(signals),
            "scope_count": len(symbols) * len(timeframes),
            "side_run_count": expected_side_runs,
            "strategy": "SIGNAL_GATED",
            "mode": "EXPANDING",
            "grid": {
                "exit_distance_model": "PAPER_POLICY",
                "stop_loss_percent": PRODUCTION_STOP_PERCENT,
                "target1_net_risk_reward": round(
                    PRODUCTION_TARGET_PERCENT / PRODUCTION_STOP_PERCENT,
                    4,
                ),
                "target1_base_distance_percent": PRODUCTION_TARGET_PERCENT,
                "target1_close_fraction": PAPER_TARGET1_FRACTION,
                "target2_base_distance_percent": PAPER_TARGET2_PERCENT,
                "max_hold_hours": PAPER_MAX_HOLD_HOURS,
                "target_adjustment": "FIXED_LEVELS_COSTS_APPLIED_TO_FILLS",
                "configured_max_risk_percent": PRODUCTION_MAX_RISK_PERCENT,
            },
        },
        "summary": {
            "completed_side_runs": completed,
            "failed_side_runs": failed,
            "contract_passes": contract_passes,
            "architecture_gate_passes": architecture_passes,
            "promotion_allowed": False,
            "promotion_note": (
                "Walk-forward evidence cannot unlock live promotion; the governed "
                "paper-observation requirements remain mandatory."
            ),
        },
        "records": records,
    }


def _markdown_report(payload):
    summary = payload["summary"]
    scope = payload["scope"]
    lines = [
        "# QuantPulseAI Complete Walk-Forward Validation Report",
        "",
        f"- Status: {payload['status']}",
        f"- Data cutoff: {payload['as_of']}",
        f"- Symbols: {', '.join(scope['symbols'])}",
        f"- Timeframes: {', '.join(scope['timeframes'])}",
        f"- Directions tested: {', '.join(scope['signals'])}",
        (
            f"- Exit policy: {PAPER_STAGED_EXIT_POLICY}; "
            f"{PAPER_STOP_LOSS_PERCENT}% stop; T1 {PAPER_TARGET1_PERCENT}% "
            f"closes {PAPER_TARGET1_FRACTION:.0%}; T2 {PAPER_TARGET2_PERCENT}% "
            f"closes the remainder; {PAPER_MAX_HOLD_HOURS}h maximum hold"
        ),
        "- Position risk: confidence-tiered up to 1% of account equity",
        f"- Completed side runs: {summary['completed_side_runs']} / {scope['side_run_count']}",
        f"- Contract passes: {summary['contract_passes']} / {scope['side_run_count']}",
        f"- Architecture gate passes: {summary['architecture_gate_passes']} / {scope['side_run_count']}",
        "- Promotion allowed: No (paper-observation gates remain mandatory)",
        "",
        "## Results",
        "",
        "| Symbol | TF | Side | Contract | Gate | Folds | OOS trades | Return % | Win % | PF | Max DD % | Sharpe |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in payload["records"]:
        lines.append(
            "| {symbol} | {timeframe} | {signal} | {contract} | {gate} | "
            "{folds} | {trades} | {ret} | {win} | {pf} | {dd} | {sharpe} |".format(
                symbol=item.get("symbol"),
                timeframe=item.get("timeframe"),
                signal=item.get("signal"),
                contract=item.get("contract_status") or item.get("status"),
                gate=item.get("architecture_gate_status") or "-",
                folds=item.get("fold_count") or 0,
                trades=item.get("oos_total_trades") or 0,
                ret=_display(item.get("oos_total_return_percent")),
                win=_display(item.get("oos_win_rate")),
                pf=_display(item.get("oos_profit_factor")),
                dd=_display(item.get("oos_max_drawdown_percent")),
                sharpe=_display(item.get("oos_annualized_sharpe")),
            )
        )
    lines.extend(["", "## Blockers", ""])
    for item in payload["records"]:
        blockers = item.get("blocked_by") or []
        if blockers:
            lines.append(
                f"- {item['symbol']} {item['timeframe']} {item['signal']}: "
                + "; ".join(blockers)
            )
    if not any(item.get("blocked_by") for item in payload["records"]):
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _latest_hourly_common_cutoff(symbols):
    db = SessionLocal()
    try:
        latest = []
        for symbol in symbols:
            value = (
                db.query(func.max(MarketCandle.close_time))
                .filter(MarketCandle.symbol == symbol)
                .filter(MarketCandle.timeframe == "1h")
                .filter(MarketCandle.is_final.is_(True))
                .scalar()
            )
            if value is None:
                raise ValueError(f"No finalized 1h candle found for {symbol}")
            latest.append(value)
        cutoff = min(latest)
        return cutoff.replace(tzinfo=timezone.utc) if cutoff.tzinfo is None else cutoff
    finally:
        db.close()


def _load_checkpoint(path, symbol):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("source") == RUN_VERSION and payload.get("symbol") == symbol:
            return payload
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass
    return {
        "source": RUN_VERSION,
        "symbol": symbol,
        "status": "QUEUED",
        "updated_at": None,
        "records": [],
    }


def _write_checkpoint(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def _validate_scope(symbols, timeframes, signals):
    unsupported = [item for item in timeframes if item not in DEFAULT_TIMEFRAMES]
    if unsupported:
        raise ValueError(f"Unsupported official timeframes: {unsupported}")
    invalid_signals = [item for item in signals if item not in DEFAULT_SIGNALS]
    if invalid_signals:
        raise ValueError(f"Unsupported signals: {invalid_signals}")
    if not symbols or not timeframes or not signals:
        raise ValueError("symbols, timeframes, and signals cannot be empty")


def _parse_as_of(value):
    if value is None or isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed is None:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _csv(value, *, upper=False):
    records = []
    for item in str(value or "").split(","):
        normalized = item.strip().upper() if upper else item.strip()
        if normalized and normalized not in records:
            records.append(normalized)
    return tuple(records)


def _display(value):
    return "-" if value is None else str(value)


def _outputs_root():
    return Path(__file__).resolve().parents[1] / "outputs"


if __name__ == "__main__":
    main()
