import hashlib
import hmac
import json
import time
from datetime import datetime
from urllib.parse import urlencode

import requests

from app.config import get_settings
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class LeverageBracketCollector:
    URL = "https://fapi.binance.com/fapi/v1/leverageBracket"

    def __init__(self, api_key=None, api_secret=None):
        settings = get_settings()
        self.api_key = api_key or settings.binance_api_key
        self.api_secret = api_secret or settings.binance_api_secret
        self.last_status = "NOT_REQUESTED"

    def get_brackets(self, symbol):
        if not self.api_key or not self.api_secret:
            self.last_status = "CREDENTIALS_UNAVAILABLE"
            return []

        timestamp_ms = int(time.time() * 1000)
        unsigned = {
            "symbol": symbol,
            "recvWindow": 5000,
            "timestamp": timestamp_ms,
        }
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            urlencode(unsigned).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params = {**unsigned, "signature": signature}
        try:
            response = requests.get(
                self.URL,
                params=params,
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=20,
            )
            response.raise_for_status()
            records = _parse_bracket_payload(
                symbol,
                response.json(),
                effective_at=datetime.utcfromtimestamp(timestamp_ms / 1000),
            )
            self.last_status = "READY" if records else "NO_DATA"
            return records
        except Exception as ex:
            self.last_status = (
                "TRANSIENT_UNAVAILABLE"
                if is_transient_network_error(ex)
                else "ERROR"
            )
            if self.last_status == "ERROR":
                print(
                    f"Leverage bracket error {symbol}: "
                    f"{classify_network_error(ex)}"
                )
            return []


def _parse_bracket_payload(symbol, payload, *, effective_at):
    candidates = payload if isinstance(payload, list) else [payload]
    contract = next(
        (
            item
            for item in candidates
            if isinstance(item, dict)
            and str(item.get("symbol") or symbol).upper() == symbol.upper()
        ),
        None,
    )
    if contract is None:
        return []
    brackets = contract.get("brackets")
    if not isinstance(brackets, list):
        return []
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    snapshot_version = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    records = []
    for item in brackets:
        try:
            records.append(
                {
                    "venue": "BINANCE",
                    "symbol": symbol.upper(),
                    "snapshot_version": snapshot_version,
                    "effective_at": effective_at,
                    "bracket_number": int(item["bracket"]),
                    "notional_floor": float(item["notionalFloor"]),
                    "notional_cap": float(item["notionalCap"]),
                    "initial_leverage": float(item["initialLeverage"]),
                    "maintenance_margin_rate": float(item["maintMarginRatio"]),
                    "maintenance_amount": float(item.get("cum") or 0),
                    "source": "BINANCE_LEVERAGE_BRACKET",
                }
            )
        except (KeyError, TypeError, ValueError):
            return []
    return records
