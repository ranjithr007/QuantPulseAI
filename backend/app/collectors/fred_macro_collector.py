from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from hashlib import sha256
from threading import RLock
from time import monotonic

import requests


FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_PROVIDER = "FRED"
MINIMUM_VERIFIED_SERIES = 5
CORE_SERIES = {"DGS2", "DGS10", "DTWEXBGS"}

SERIES_SPECS = {
    "DGS2": {
        "label": "US 2-year Treasury yield",
        "kind": "basis_points_inverse",
        "maximum": 20,
        "max_age_days": 7,
        "positive_reason": "US 2-year Treasury yield is falling",
        "negative_reason": "US 2-year Treasury yield is rising",
    },
    "DGS10": {
        "label": "US 10-year Treasury yield",
        "kind": "basis_points_inverse",
        "maximum": 15,
        "max_age_days": 7,
        "positive_reason": "US 10-year Treasury yield is falling",
        "negative_reason": "US 10-year Treasury yield is rising",
    },
    "DTWEXBGS": {
        "label": "Broad US dollar index",
        "kind": "percent_inverse",
        "multiplier": 20,
        "maximum": 20,
        "max_age_days": 7,
        "positive_reason": "Broad US dollar index is weakening",
        "negative_reason": "Broad US dollar index is strengthening",
    },
    "WALCL": {
        "label": "Federal Reserve balance sheet",
        "kind": "percent_direct",
        "multiplier": 15,
        "maximum": 15,
        "max_age_days": 14,
        "positive_reason": "Federal Reserve balance sheet is expanding",
        "negative_reason": "Federal Reserve balance sheet is contracting",
    },
    "RRPONTSYD": {
        "label": "Overnight reverse repo",
        "kind": "percent_inverse",
        "multiplier": 0.25,
        "maximum": 10,
        "max_age_days": 7,
        "positive_reason": "Overnight reverse repo balance is falling",
        "negative_reason": "Overnight reverse repo balance is rising",
    },
    "WTREGEN": {
        "label": "Treasury General Account",
        "kind": "percent_inverse",
        "multiplier": 1,
        "maximum": 15,
        "max_age_days": 14,
        "positive_reason": "Treasury General Account is falling and releasing liquidity",
        "negative_reason": "Treasury General Account is rising and absorbing liquidity",
    },
    "DFF": {
        "label": "Effective federal funds rate",
        "kind": "basis_points_inverse",
        "maximum": 10,
        "max_age_days": 7,
        "positive_reason": "Effective federal funds rate is falling",
        "negative_reason": "Effective federal funds rate is rising",
    },
    "VIXCLS": {
        "label": "CBOE volatility index",
        "kind": "percent_inverse",
        "multiplier": 0.5,
        "maximum": 10,
        "max_age_days": 7,
        "positive_reason": "Market volatility is falling",
        "negative_reason": "Market volatility is rising",
    },
}


class FredMacroCollector:
    _cache = {}
    _cache_lock = RLock()

    def __init__(self, api_key, *, timeout_seconds=10, cache_seconds=1800):
        self.api_key = str(api_key or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.cache_seconds = max(0, int(cache_seconds))

    def collect(self, *, force_refresh=False, now=None):
        observed_at = now or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        if not self.api_key:
            return self._unavailable(
                "NOT_CONFIGURED",
                observed_at,
                "FRED_API_KEY is not configured",
            )

        cache_key = sha256(self.api_key.encode("utf-8")).hexdigest()
        if not force_refresh:
            cached = self._cached(cache_key)
            if cached is not None:
                return cached

        series = {}
        errors = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._fetch_series, series_id): series_id
                for series_id in SERIES_SPECS
            }
            for future in as_completed(futures):
                series_id = futures[future]
                try:
                    series[series_id] = future.result()
                except Exception as exc:
                    errors[series_id] = type(exc).__name__

        payload = self._build_payload(series, errors, observed_at)
        self._store_cache(cache_key, payload)
        return payload

    def _fetch_series(self, series_id):
        response = requests.get(
            FRED_OBSERVATIONS_URL,
            params={
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 10,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        observations = []
        for item in response.json().get("observations") or []:
            try:
                value = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            observations.append(
                {
                    "date": str(item.get("date") or ""),
                    "value": value,
                }
            )
            if len(observations) == 2:
                break
        if len(observations) < 2:
            raise ValueError(f"{series_id} returned fewer than two usable observations")
        return observations

    def _build_payload(self, series, errors, observed_at):
        components = {}
        stale_series = []
        reasons = []
        total_score = 0.0
        today = observed_at.date()

        for series_id, observations in series.items():
            spec = SERIES_SPECS[series_id]
            latest, previous = observations[0], observations[1]
            contribution, change = _series_contribution(
                latest["value"],
                previous["value"],
                spec,
            )
            data_date = _date(latest["date"])
            age_days = (today - data_date).days if data_date else None
            is_stale = age_days is None or age_days > spec["max_age_days"]
            if is_stale:
                stale_series.append(series_id)
            else:
                total_score += contribution
                if contribution >= 2:
                    reasons.append((abs(contribution), spec["positive_reason"]))
                elif contribution <= -2:
                    reasons.append((abs(contribution), spec["negative_reason"]))
            components[series_id] = {
                "label": spec["label"],
                "latest": latest["value"],
                "previous": previous["value"],
                "change": round(change, 6),
                "contribution": round(contribution, 2),
                "data_date": latest["date"],
                "age_days": age_days,
                "is_stale": is_stale,
            }

        usable = set(series) - set(stale_series)
        verified = CORE_SERIES.issubset(usable) and len(usable) >= MINIMUM_VERIFIED_SERIES
        status = "VERIFIED" if verified else "DEGRADED"
        reason_text = [item[1] for item in sorted(reasons, reverse=True)[:5]]
        data_dates = [
            item["data_date"]
            for item in components.values()
            if item.get("data_date") and not item.get("is_stale")
        ]
        return {
            "status": status,
            "provider": FRED_PROVIDER,
            "source": "FRED_SERIES_OBSERVATIONS_V1",
            "macro_score": round(_clamp(total_score, -100, 100), 2),
            "series": components,
            "series_count": len(usable),
            "required_series_count": MINIMUM_VERIFIED_SERIES,
            "core_series": sorted(CORE_SERIES),
            "stale_series": sorted(stale_series),
            "errors": errors,
            "reasons": reason_text,
            "data_timestamp": max(data_dates) if data_dates else None,
            "observed_at": observed_at.isoformat(),
            "advisory_only": True,
        }

    def _cached(self, cache_key):
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is None:
                return None
            cached_at, payload = cached
            if monotonic() - cached_at > self.cache_seconds:
                self._cache.pop(cache_key, None)
                return None
            return payload

    def _store_cache(self, cache_key, payload):
        with self._cache_lock:
            self._cache[cache_key] = (monotonic(), payload)

    @classmethod
    def clear_cache(cls):
        with cls._cache_lock:
            cls._cache.clear()

    @staticmethod
    def _unavailable(status, observed_at, reason):
        return {
            "status": status,
            "provider": FRED_PROVIDER,
            "source": "FRED_SERIES_OBSERVATIONS_V1",
            "macro_score": None,
            "series": {},
            "series_count": 0,
            "required_series_count": MINIMUM_VERIFIED_SERIES,
            "core_series": sorted(CORE_SERIES),
            "stale_series": [],
            "errors": {},
            "reasons": [reason],
            "data_timestamp": None,
            "observed_at": observed_at.isoformat(),
            "advisory_only": True,
        }


def _series_contribution(latest, previous, spec):
    change = latest - previous
    kind = spec["kind"]
    maximum = float(spec["maximum"])
    if kind == "basis_points_inverse":
        contribution = -(change * 100) * 2
    else:
        percent_change = (change / abs(previous)) * 100 if previous else 0.0
        change = percent_change
        direction = -1 if kind == "percent_inverse" else 1
        contribution = direction * percent_change * float(spec["multiplier"])
    return _clamp(contribution, -maximum, maximum), change


def _date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, float(value)))
