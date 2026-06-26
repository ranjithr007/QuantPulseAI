from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from app.intelligence.contradiction_engine import build_contradiction_report
from app.repositories.candle_repository import get_latest_candles
from app.repositories.data_quality_event_repository import DataQualityEventRepository


DATA_QUALITY_LEDGER_VERSION = "data_quality_ledger_v1"
CRITICAL_STALE_INPUTS = {"candle", "feature", "regime", "orderflow", "smc"}


@dataclass(frozen=True)
class DataQualityPolicy:
    min_volume_ratio: float = 0.25
    max_volume_spike_ratio: float = 3.0
    max_price_spike_percent: float = 10.0
    max_abs_funding_rate: float = 0.0015
    max_abs_open_interest_change_percent: float = 15.0
    cross_source_block_score: int = 60


def build_data_quality_observability(
    db,
    symbol,
    timeframe="5m",
    stale_after_seconds=900,
    limit=20,
    policy=None,
    persist=True,
):
    policy = policy or DataQualityPolicy()
    observed_at = datetime.utcnow()
    report = build_contradiction_report(db, symbol, timeframe, stale_after_seconds)
    candles = get_latest_candles(db, symbol, timeframe, limit=limit)
    events = build_data_quality_events(
        report,
        candles=candles,
        policy=policy,
        observed_at=observed_at,
    )
    persisted_events = (
        DataQualityEventRepository().record_events(db, events)
        if persist and events
        else []
    )
    effective_events = persisted_events or events
    blocking_actions = [event["reason"] for event in events if event["blocked"]]
    blocked = bool(blocking_actions) or not report.get("trade_allowed", True)

    return {
        "source": "data_quality_ledger",
        "ledger_version": DATA_QUALITY_LEDGER_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "policy": asdict(policy),
        "decision": "BLOCK" if blocked else "ALLOW",
        "blocked": blocked,
        "blocking_actions": blocking_actions,
        "report": report,
        "events": effective_events,
        "summary": _summarize_events(events),
        "observed_at": observed_at.isoformat(),
    }


def build_data_quality_events(report, candles=None, policy=None, observed_at=None):
    policy = policy or DataQualityPolicy()
    observed_at = _as_datetime(observed_at) or datetime.utcnow()
    report = report or {}
    candles = _sorted_candles(candles or [])
    latest = candles[0] if candles else None
    previous = candles[1] if len(candles) > 1 else None
    symbol = str(report.get("symbol") or _value(latest, "symbol") or "UNKNOWN")
    timeframe = str(report.get("timeframe") or _value(latest, "timeframe") or "5m")
    events = []

    freshness = report.get("freshness") or {}
    stale_sources = [
        name
        for name, status in freshness.items()
        if name in CRITICAL_STALE_INPUTS and _is_stale(status)
    ]
    if stale_sources:
        for source in stale_sources:
            events.append(
                _event(
                    symbol,
                    timeframe,
                    source=source,
                    category="STALENESS",
                    severity="critical",
                    blocked=True,
                    reason=f"{source.replace('_', ' ').title()} input is stale",
                    details={
                        "freshness": freshness.get(source),
                        "trade_allowed": report.get("trade_allowed"),
                    },
                    observed_at=observed_at,
                    effective_at=_effective_at(report, latest, observed_at),
                )
            )

    conflicts = report.get("conflicts") or []
    if conflicts:
        conflict_score = _as_float(report.get("conflict_score")) or 0.0
        blocked = bool(
            not report.get("trade_allowed", True)
            or conflict_score >= policy.cross_source_block_score
        )
        severity = (
            "critical"
            if blocked or any(_value(item, "severity") == "critical" for item in conflicts)
            else "warning"
        )
        reasons = [
            _value(item, "detail")
            for item in conflicts
            if _value(item, "detail")
        ]
        events.append(
            _event(
                symbol,
                timeframe,
                source="contradiction_engine",
                category="CROSS_SOURCE",
                severity=severity,
                blocked=blocked,
                reason=reasons[0] if reasons else "Cross-source contradictions detected",
                details={
                    "conflict_score": conflict_score,
                    "trade_allowed": report.get("trade_allowed"),
                    "conflicts": conflicts,
                    "reasons": reasons,
                },
                observed_at=observed_at,
                effective_at=_effective_at(report, latest, observed_at),
            )
        )

    if latest is None:
        events.append(
            _event(
                symbol,
                timeframe,
                source="market_candles",
                category="MISSING_DATA",
                severity="critical",
                blocked=True,
                reason="No latest candle available",
                details={"report_status": report.get("status") or "UNKNOWN"},
                observed_at=observed_at,
                effective_at=_effective_at(report, latest, observed_at),
            )
        )
    else:
        latest_volume = _as_float(_value(latest, "volume"))
        if latest_volume is not None:
            prior_volumes = [
                volume
                for volume in (_as_float(_value(item, "volume")) for item in candles[1:])
                if volume is not None
            ]
            if prior_volumes:
                average_volume = mean(prior_volumes)
                volume_ratio = latest_volume / average_volume if average_volume else None
                if latest_volume <= 0 or (
                    volume_ratio is not None and volume_ratio <= policy.min_volume_ratio
                ):
                    events.append(
                        _event(
                            symbol,
                            timeframe,
                            source="market_candles",
                            category="VOLUME",
                            severity="critical",
                            blocked=True,
                            reason="Latest volume is below the recent average",
                            details={
                                "latest_volume": latest_volume,
                                "average_prior_volume": round(average_volume, 4),
                                "volume_ratio": round(volume_ratio, 4) if volume_ratio else None,
                            },
                            observed_at=observed_at,
                            effective_at=_effective_at(report, latest, observed_at),
                        )
                    )
                elif volume_ratio is not None and volume_ratio >= policy.max_volume_spike_ratio:
                    events.append(
                        _event(
                            symbol,
                            timeframe,
                            source="market_candles",
                            category="VOLUME",
                            severity="warning",
                            blocked=False,
                            reason="Latest volume is well above the recent average",
                            details={
                                "latest_volume": latest_volume,
                                "average_prior_volume": round(average_volume, 4),
                                "volume_ratio": round(volume_ratio, 4),
                            },
                            observed_at=observed_at,
                            effective_at=_effective_at(report, latest, observed_at),
                        )
                    )
            elif latest_volume <= 0:
                events.append(
                    _event(
                        symbol,
                        timeframe,
                        source="market_candles",
                        category="VOLUME",
                        severity="critical",
                        blocked=True,
                        reason="Latest volume is zero or missing",
                        details={"latest_volume": latest_volume},
                        observed_at=observed_at,
                        effective_at=_effective_at(report, latest, observed_at),
                    )
                )

        if previous is not None:
            price_change_pct = _percent_change(
                _as_float(_value(previous, "close_price")),
                _as_float(_value(latest, "close_price")),
            )
            if price_change_pct is not None and abs(price_change_pct) >= policy.max_price_spike_percent:
                events.append(
                    _event(
                        symbol,
                        timeframe,
                        source="market_candles",
                        category="SPIKE",
                        severity="critical" if abs(price_change_pct) >= policy.max_price_spike_percent * 1.5 else "warning",
                        blocked=abs(price_change_pct) >= policy.max_price_spike_percent * 1.5,
                        reason="Price moved sharply relative to the prior candle",
                        details={
                            "price_change_pct": round(price_change_pct, 4),
                            "latest_close_price": _as_float(_value(latest, "close_price")),
                            "previous_close_price": _as_float(_value(previous, "close_price")),
                        },
                        observed_at=observed_at,
                        effective_at=_effective_at(report, latest, observed_at),
                    )
                )

    funding_rate = _as_float(report.get("funding_rate"))
    if funding_rate is not None and abs(funding_rate) >= policy.max_abs_funding_rate:
        events.append(
            _event(
                symbol,
                timeframe,
                source="funding",
                category="FUNDING",
                severity="critical" if abs(funding_rate) >= policy.max_abs_funding_rate * 2 else "warning",
                blocked=abs(funding_rate) >= policy.max_abs_funding_rate * 2,
                reason="Funding rate is elevated",
                details={
                    "funding_rate": funding_rate,
                    "threshold": policy.max_abs_funding_rate,
                },
                observed_at=observed_at,
                effective_at=_effective_at(report, latest, observed_at),
            )
        )

    open_interest_change_pct = _as_float(report.get("open_interest_change_pct"))
    if (
        open_interest_change_pct is not None
        and abs(open_interest_change_pct) >= policy.max_abs_open_interest_change_percent
    ):
        events.append(
            _event(
                symbol,
                timeframe,
                source="open_interest",
                category="OPEN_INTEREST",
                severity="critical"
                if abs(open_interest_change_pct)
                >= policy.max_abs_open_interest_change_percent * 1.5
                else "warning",
                blocked=abs(open_interest_change_pct)
                >= policy.max_abs_open_interest_change_percent * 1.5,
                reason="Open interest change is elevated",
                details={
                    "open_interest_change_pct": open_interest_change_pct,
                    "threshold": policy.max_abs_open_interest_change_percent,
                },
                observed_at=observed_at,
                effective_at=_effective_at(report, latest, observed_at),
            )
        )

    if not events and report.get("status") == "INVALIDATED":
        events.append(
            _event(
                symbol,
                timeframe,
                source="contradiction_engine",
                category="MISSING_DATA",
                severity="critical",
                blocked=True,
                reason="Data quality check invalidated the trade setup",
                details={
                    "status": report.get("status"),
                    "trade_allowed": report.get("trade_allowed"),
                },
                observed_at=observed_at,
                effective_at=_effective_at(report, latest, observed_at),
            )
        )

    return events


def _event(
    symbol,
    timeframe,
    source,
    category,
    severity,
    blocked,
    reason,
    details,
    observed_at,
    effective_at,
):
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": source,
        "category": category,
        "severity": severity,
        "status": "BLOCKED" if blocked else "WARN",
        "blocked": bool(blocked),
        "reason": reason,
        "details": details,
        "observed_at": observed_at.isoformat(),
        "effective_at": effective_at.isoformat() if effective_at else observed_at.isoformat(),
    }


def _summarize_events(events):
    by_category = {}
    by_severity = {}
    for event in events:
        by_category[event["category"]] = by_category.get(event["category"], 0) + 1
        by_severity[event["severity"]] = by_severity.get(event["severity"], 0) + 1

    blocked = [event for event in events if event["blocked"]]

    return {
        "total_events": len(events),
        "blocked_events": len(blocked),
        "warn_events": len(events) - len(blocked),
        "by_category": dict(sorted(by_category.items())),
        "by_severity": dict(sorted(by_severity.items())),
    }


def _effective_at(report, latest, fallback):
    if latest is not None and _value(latest, "candle_time") is not None:
        return _as_datetime(_value(latest, "candle_time")) or fallback
    if report.get("candle_time") is not None:
        return _as_datetime(report.get("candle_time")) or fallback
    return fallback


def _sorted_candles(candles):
    return sorted(
        candles,
        key=lambda item: _as_datetime(_value(item, "candle_time")) or datetime.min,
        reverse=True,
    )


def _is_stale(status):
    return bool(status and status.get("is_stale"))


def _value(item, name):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _as_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _percent_change(previous, current):
    if previous in (None, 0) or current is None:
        return None
    try:
        return ((float(current) - float(previous)) / float(previous)) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return None
