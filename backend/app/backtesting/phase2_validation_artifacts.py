import json
from datetime import datetime
from pathlib import Path


def persist_phase2_validation_artifact(report, walk_forward_result, *, symbol, timeframe, signal, as_of=None):
    timestamp = _artifact_timestamp(as_of)
    output_dir = _outputs_root() / "phase2_validation_reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"{_safe(symbol)}_{_safe(timeframe)}_{_safe(signal)}_{timestamp}"
    json_path = output_dir / f"{base_name}.json"
    md_path = output_dir / f"{base_name}.md"

    payload = {
        "saved_at": _as_datetime(as_of).isoformat(),
        "scope": {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": signal,
        },
        "report": report,
        "walk_forward_result": walk_forward_result,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_summary(report, symbol, timeframe, signal), encoding="utf-8")

    return {
        "artifact_id": base_name,
        "saved": True,
        "saved_at": payload["saved_at"],
        "directory": str(output_dir),
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "scope": payload["scope"],
        "overall_status": dict(report or {}).get("overall_status"),
        "architecture_gate_status": dict((report or {}).get("architecture_gate") or {}).get("status"),
    }


def list_phase2_validation_artifacts(*, symbol=None, timeframe=None, signal=None, limit=10):
    records = []
    for json_path in sorted(_artifact_dir().glob("*.json"), reverse=True):
        payload = _read_payload(json_path)
        if not payload:
            continue
        scope = dict(payload.get("scope") or {})
        if symbol and str(scope.get("symbol", "")).upper() != str(symbol).upper():
            continue
        if timeframe and str(scope.get("timeframe", "")) != str(timeframe):
            continue
        if signal and str(scope.get("signal", "")).upper() != str(signal).upper():
            continue
        records.append(_history_record(json_path, payload))
        if len(records) >= int(limit):
            break
    return records


def load_phase2_validation_artifact(artifact_id):
    safe_id = _safe(artifact_id)
    json_path = _artifact_dir() / f"{safe_id}.json"
    payload = _read_payload(json_path)
    if payload is None:
        return None
    return {
        "artifact": _history_record(json_path, payload),
        "payload": payload,
    }


def summarize_phase2_validation_artifacts(*, symbol=None, timeframe=None, signal=None, limit=20):
    grouped = {}
    for json_path in sorted(_artifact_dir().glob("*.json"), reverse=True):
        payload = _read_payload(json_path)
        if not payload:
            continue
        scope = dict(payload.get("scope") or {})
        if symbol and str(scope.get("symbol", "")).upper() != str(symbol).upper():
            continue
        if timeframe and str(scope.get("timeframe", "")) != str(timeframe):
            continue
        if signal and str(scope.get("signal", "")).upper() != str(signal).upper():
            continue
        key = (
            str(scope.get("symbol", "")).upper(),
            str(scope.get("timeframe", "")),
            str(scope.get("signal", "")).upper(),
        )
        grouped.setdefault(key, []).append((json_path, payload))

    records = []
    for items in grouped.values():
        latest_json_path, latest_payload = items[0]
        previous_payload = items[1][1] if len(items) > 1 else None
        records.append(_scope_summary_record(latest_json_path, latest_payload, previous_payload, len(items)))

    records.sort(key=lambda item: item.get("saved_at") or "", reverse=True)
    return records[: int(limit)]


def _markdown_summary(report, symbol, timeframe, signal):
    gate = dict((report or {}).get("architecture_gate") or {})
    metrics = dict((report or {}).get("derived_metrics") or {})
    blocked = list((report or {}).get("blocked_by") or [])

    lines = [
        "# QuantPulseAI Phase 2 Validation Artifact",
        "",
        f"- Symbol: {symbol}",
        f"- Timeframe: {timeframe}",
        f"- Signal: {signal}",
        f"- Overall status: {(report or {}).get('overall_status', '-')}",
        f"- Architecture gate: {gate.get('status', '-')}",
        "",
        "## Derived metrics",
        "",
        f"- OOS trades: {metrics.get('out_of_sample_total_trades', '-')}",
        f"- OOS return %: {metrics.get('out_of_sample_total_return_percent', '-')}",
        f"- OOS profit factor: {metrics.get('out_of_sample_profit_factor', '-')}",
        f"- OOS win rate: {metrics.get('out_of_sample_win_rate', '-')}",
        f"- OOS max drawdown %: {metrics.get('out_of_sample_max_drawdown_percent', '-')}",
        f"- OOS payoff ratio: {metrics.get('out_of_sample_payoff_ratio', '-')}",
        "",
        "## Gate checks",
        "",
    ]

    for check in gate.get("checks") or []:
        lines.append(
            f"- {check.get('name')}: {check.get('status')} (actual={check.get('actual')}, threshold={check.get('threshold')}, comparison={check.get('comparison')})"
        )
    lines.extend(
        [
            "",
            "## Blockers",
            "",
        ]
    )
    if blocked:
        lines.extend([f"- {item}" for item in blocked])
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Next action",
            "",
            (report or {}).get("next_action", "-"),
            "",
        ]
    )
    return "\n".join(lines)


def _outputs_root():
    current = Path(__file__).resolve()
    for ancestor in current.parents:
        candidate = ancestor / "outputs"
        if candidate.exists():
            return candidate
    return current.parents[4] / "outputs"


def _artifact_dir():
    return _outputs_root() / "phase2_validation_reports"


def _safe(value):
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "").strip()) or "unknown"


def _artifact_timestamp(value):
    return _as_datetime(value).strftime("%Y%m%d_%H%M%S")


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    return datetime.utcnow()


def _read_payload(json_path):
    try:
        return json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _history_record(json_path, payload):
    report = dict((payload or {}).get("report") or {})
    scope = dict((payload or {}).get("scope") or {})
    markdown_path = Path(json_path).with_suffix(".md")
    return {
        "artifact_id": Path(json_path).stem,
        "saved_at": payload.get("saved_at"),
        "scope": scope,
        "overall_status": report.get("overall_status"),
        "architecture_gate_status": dict(report.get("architecture_gate") or {}).get("status"),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "exists": Path(json_path).exists(),
    }


def _scope_summary_record(json_path, latest_payload, previous_payload, sample_count):
    latest_report = dict((latest_payload or {}).get("report") or {})
    previous_report = dict((previous_payload or {}).get("report") or {})
    latest_metrics = dict(latest_report.get("derived_metrics") or {})
    previous_metrics = dict(previous_report.get("derived_metrics") or {})
    history_record = _history_record(json_path, latest_payload)
    return {
        **history_record,
        "sample_count": int(sample_count),
        "previous_saved_at": previous_payload.get("saved_at") if previous_payload else None,
        "status_change": _status_change(
            latest_report.get("overall_status"),
            previous_report.get("overall_status"),
        ),
        "drift": {
            "out_of_sample_total_return_percent": _delta(
                latest_metrics.get("out_of_sample_total_return_percent"),
                previous_metrics.get("out_of_sample_total_return_percent"),
            ),
            "out_of_sample_profit_factor": _delta(
                latest_metrics.get("out_of_sample_profit_factor"),
                previous_metrics.get("out_of_sample_profit_factor"),
            ),
            "out_of_sample_win_rate": _delta(
                latest_metrics.get("out_of_sample_win_rate"),
                previous_metrics.get("out_of_sample_win_rate"),
            ),
            "out_of_sample_max_drawdown_percent": _delta(
                latest_metrics.get("out_of_sample_max_drawdown_percent"),
                previous_metrics.get("out_of_sample_max_drawdown_percent"),
            ),
            "out_of_sample_payoff_ratio": _delta(
                latest_metrics.get("out_of_sample_payoff_ratio"),
                previous_metrics.get("out_of_sample_payoff_ratio"),
            ),
        },
        "latest_metrics": latest_metrics,
        "previous_metrics": previous_metrics if previous_payload else None,
    }


def _delta(current, previous):
    try:
        if current is None or previous is None:
            return None
        return round(float(current) - float(previous), 4)
    except (TypeError, ValueError):
        return None


def _status_change(current, previous):
    current_value = str(current or "")
    previous_value = str(previous or "")
    if not previous_value:
        return "FIRST_SAMPLE"
    if current_value == previous_value:
        return "UNCHANGED"
    return f"{previous_value}_TO_{current_value}"
