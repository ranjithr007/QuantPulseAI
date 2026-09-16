import requests
import time
from datetime import datetime

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class OpenInterestCollector:
    def __init__(
        self,
        *,
        timeout_seconds=20,
        max_attempts=3,
        retry_delay_seconds=3,
    ):
        self.timeout_seconds = max(1, float(timeout_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_seconds = max(0, float(retry_delay_seconds))

    def get_data(
        self,
        symbol,
    ):
        url = "https://fapi.binance.com/fapi/v1/openInterest"

        last_error = None

        for attempt in range(self.max_attempts):
            try:
                response = requests.get(
                    url,
                    params={
                        "symbol": symbol,
                    },
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()

                payload = response.json()
                if isinstance(payload, list):
                    payload = payload[0] if payload else None

                if isinstance(payload, dict) and "openInterest" in payload:
                    open_interest = payload.get("openInterest")
                else:
                    open_interest = None

                if open_interest is None:
                    return None

                return {
                    "symbol": symbol,
                    "value": float(open_interest),
                    "time": datetime.utcnow(),
                }
            except Exception as ex:
                last_error = ex
                if attempt < self.max_attempts - 1:
                    time.sleep(self.retry_delay_seconds)

        if last_error is not None:
            if not is_transient_network_error(last_error):
                print(f"Open interest error {symbol}: {classify_network_error(last_error)}")

        return None
