import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


RESEARCH_EXPORT_VERSION = "cluster_research_tables_v1"
TABLE_SCHEMAS = {
    "market_state": (
        "decision_time",
        "entry_time",
        "symbol",
        "timeframe",
        "cluster",
        "side",
        "confidence",
        "regime",
        "trend_score",
        "momentum_score",
        "feature_score",
        "atr",
        "feature_source",
        "timeframe_stack",
    ),
    "symbol_behavior": (
        "symbol",
        "cluster",
        "candidate_count",
        "accepted_count",
        "rejected_count",
        "wins",
        "losses",
        "breakeven",
        "win_rate",
        "net_pnl",
        "average_confidence",
        "average_duration_candles",
        "average_mfe_r",
        "average_mae_r",
    ),
    "correlation_exposure": (
        "entry_time",
        "symbol",
        "cluster",
        "side",
        "notional",
        "open_positions",
        "gross_exposure",
        "gross_exposure_percent",
        "cluster_exposure",
        "cluster_exposure_percent",
    ),
    "trade_paths": (
        "symbol",
        "timeframe",
        "cluster",
        "side",
        "decision_time",
        "entry_time",
        "exit_time",
        "entry",
        "exit",
        "stop",
        "target",
        "exit_reason",
        "result",
        "loss_class",
        "duration_candles",
        "notional",
        "gross_pnl",
        "fees",
        "pnl",
        "pnl_percent",
        "mfe_r",
        "mae_r",
        "funding_payment",
        "liquidation_status",
    ),
}


def build_cluster_research_tables(portfolio_result):
    result = dict(portfolio_result or {})
    trades = sorted(
        (dict(trade) for trade in result.get("trades") or []),
        key=lambda trade: (
            str(trade.get("entry_time") or ""),
            str(trade.get("symbol") or ""),
            str(trade.get("side") or ""),
        ),
    )
    rejected = list(result.get("rejected_candidates") or [])
    timeframe = result.get("timeframe")

    market_state = [_market_state_row(trade, timeframe) for trade in trades]
    correlation_exposure = [_exposure_row(trade) for trade in trades]
    trade_paths = [_trade_path_row(trade, timeframe) for trade in trades]
    symbol_behavior = _symbol_behavior_rows(trades, rejected)

    return {
        "schema_version": RESEARCH_EXPORT_VERSION,
        "point_in_time_policy": {
            "market_state": "ENTRY_INFORMATION_ONLY",
            "correlation_exposure": "PROJECTED_AT_ENTRY_BEFORE_ADMISSION",
            "symbol_behavior": "POST_REPLAY_AGGREGATE",
            "trade_paths": "ENTRY_TO_EXIT_OUTCOME_PATH",
        },
        "tables": {
            "market_state": market_state,
            "symbol_behavior": symbol_behavior,
            "correlation_exposure": correlation_exposure,
            "trade_paths": trade_paths,
        },
        "row_counts": {
            "market_state": len(market_state),
            "symbol_behavior": len(symbol_behavior),
            "correlation_exposure": len(correlation_exposure),
            "trade_paths": len(trade_paths),
        },
    }


def persist_cluster_research_tables(
    portfolio_result,
    *,
    output_dir=None,
    as_of=None,
):
    tables = build_cluster_research_tables(portfolio_result)
    destination = Path(output_dir) if output_dir else _default_output_dir()
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = _as_datetime(as_of).strftime("%Y%m%dT%H%M%SZ")
    symbols = "-".join(
        sorted(str(symbol).upper() for symbol in portfolio_result.get("symbols") or [])
    ) or "PORTFOLIO"
    base_name = f"{_safe(symbols)}_{_safe(portfolio_result.get('timeframe') or 'NA')}_{timestamp}"

    files = {}
    for table_name, schema in TABLE_SCHEMAS.items():
        path = destination / f"{base_name}_{table_name}.csv"
        _write_csv(path, schema, tables["tables"][table_name])
        files[table_name] = _file_record(path)

    json_path = destination / f"{base_name}_tables.json"
    json_path.write_text(
        json.dumps(tables, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    files["json"] = _file_record(json_path)

    manifest = {
        "export_version": RESEARCH_EXPORT_VERSION,
        "artifact_id": base_name,
        "generated_at": _as_datetime(as_of).isoformat(),
        "source_engine_version": portfolio_result.get("engine_version"),
        "scope": {
            "symbols": sorted(portfolio_result.get("symbols") or []),
            "timeframe": portfolio_result.get("timeframe"),
            "signal": portfolio_result.get("signal"),
        },
        "point_in_time_policy": tables["point_in_time_policy"],
        "row_counts": tables["row_counts"],
        "files": files,
    }
    manifest_path = destination / f"{base_name}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        **manifest,
        "saved": True,
        "directory": str(destination.resolve()),
        "manifest_path": str(manifest_path.resolve()),
    }


def _market_state_row(trade, timeframe):
    return {
        "decision_time": trade.get("decision_time"),
        "entry_time": trade.get("entry_time"),
        "symbol": trade.get("symbol"),
        "timeframe": timeframe,
        "cluster": trade.get("cluster"),
        "side": trade.get("side"),
        "confidence": trade.get("confidence"),
        "regime": trade.get("regime"),
        "trend_score": trade.get("trend_score"),
        "momentum_score": trade.get("momentum_score"),
        "feature_score": trade.get("feature_score"),
        "atr": trade.get("atr"),
        "feature_source": trade.get("feature_source"),
        "timeframe_stack": trade.get("timeframe_stack"),
    }


def _exposure_row(trade):
    state = dict(trade.get("portfolio_state_at_entry") or {})
    return {
        "entry_time": trade.get("entry_time"),
        "symbol": trade.get("symbol"),
        "cluster": trade.get("cluster"),
        "side": trade.get("side"),
        "notional": dict(trade.get("sizing") or {}).get("notional")
        or trade.get("notional"),
        "open_positions": state.get("open_positions"),
        "gross_exposure": state.get("gross_exposure"),
        "gross_exposure_percent": state.get("gross_exposure_percent"),
        "cluster_exposure": state.get("cluster_exposure"),
        "cluster_exposure_percent": state.get("cluster_exposure_percent"),
    }


def _trade_path_row(trade, timeframe):
    excursions = dict(trade.get("excursions") or {})
    costs = dict(trade.get("execution_costs") or {})
    liquidation = dict(trade.get("liquidation") or {})
    return {
        "symbol": trade.get("symbol"),
        "timeframe": timeframe,
        "cluster": trade.get("cluster"),
        "side": trade.get("side"),
        "decision_time": trade.get("decision_time"),
        "entry_time": trade.get("entry_time"),
        "exit_time": trade.get("exit_time"),
        "entry": trade.get("entry"),
        "exit": trade.get("exit"),
        "stop": trade.get("stop"),
        "target": trade.get("target"),
        "exit_reason": trade.get("exit_reason"),
        "result": trade.get("result"),
        "loss_class": trade.get("loss_class"),
        "duration_candles": trade.get("duration_candles"),
        "notional": dict(trade.get("sizing") or {}).get("notional")
        or trade.get("notional"),
        "gross_pnl": trade.get("gross_pnl"),
        "fees": trade.get("fees"),
        "pnl": trade.get("pnl"),
        "pnl_percent": trade.get("pnl_percent"),
        "mfe_r": excursions.get("mfe_r"),
        "mae_r": excursions.get("mae_r"),
        "funding_payment": costs.get("funding_payment"),
        "liquidation_status": liquidation.get("status"),
    }


def _symbol_behavior_rows(trades, rejected):
    accepted_by_symbol = defaultdict(list)
    rejected_counts = Counter()
    clusters = {}
    for trade in trades:
        symbol = str(trade.get("symbol") or "")
        accepted_by_symbol[symbol].append(trade)
        clusters[symbol] = trade.get("cluster")
    for item in rejected:
        symbol = str(item.get("symbol") or "")
        rejected_counts[symbol] += 1
    rows = []
    for symbol in sorted(set(accepted_by_symbol) | set(rejected_counts)):
        symbol_trades = accepted_by_symbol[symbol]
        pnl_values = [float(trade.get("pnl") or 0) for trade in symbol_trades]
        wins = sum(value > 0 for value in pnl_values)
        losses = sum(value < 0 for value in pnl_values)
        rows.append(
            {
                "symbol": symbol,
                "cluster": clusters.get(symbol),
                "candidate_count": len(symbol_trades) + rejected_counts[symbol],
                "accepted_count": len(symbol_trades),
                "rejected_count": rejected_counts[symbol],
                "wins": wins,
                "losses": losses,
                "breakeven": len(symbol_trades) - wins - losses,
                "win_rate": _average_percent(wins, len(symbol_trades)),
                "net_pnl": round(sum(pnl_values), 4),
                "average_confidence": _average(
                    trade.get("confidence") for trade in symbol_trades
                ),
                "average_duration_candles": _average(
                    trade.get("duration_candles") for trade in symbol_trades
                ),
                "average_mfe_r": _average(
                    dict(trade.get("excursions") or {}).get("mfe_r")
                    for trade in symbol_trades
                ),
                "average_mae_r": _average(
                    dict(trade.get("excursions") or {}).get("mae_r")
                    for trade in symbol_trades
                ),
            }
        )
    return rows


def _write_csv(path, schema, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=schema, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: _csv_value(row.get(field))
                    for field in schema
                }
            )


def _csv_value(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return value


def _average(values):
    numeric = [
        float(value)
        for value in values
        if value is not None
    ]
    return round(sum(numeric) / len(numeric), 4) if numeric else None


def _average_percent(numerator, denominator):
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0


def _file_record(path):
    value = Path(path)
    content = value.read_bytes()
    return {
        "name": value.name,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _default_output_dir():
    current = Path(__file__).resolve()
    for ancestor in current.parents:
        candidate = ancestor / "outputs"
        if candidate.exists():
            return candidate / "portfolio_research_exports"
    return current.parents[3] / "outputs" / "portfolio_research_exports"


def _as_datetime(value):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _safe(value):
    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(value)
    ).strip("_") or "NA"
