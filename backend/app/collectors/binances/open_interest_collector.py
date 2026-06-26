import requests
import time
from datetime import datetime

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class OpenInterestCollector:
    def get_data(
        self,
        symbol,
    ):
        url = "https://fapi.binance.com/fapi/v1/openInterest"

        last_error = None

        for attempt in range(3):
            try:
                response = requests.get(
                    url,
                    params={
                        "symbol": symbol,
                    },
                    timeout=20,
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
                time.sleep(3)

        if last_error is not None:
            if not is_transient_network_error(last_error):
                print(f"Open interest error {symbol}: {classify_network_error(last_error)}")

        return None
