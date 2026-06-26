import requests
import time
from datetime import datetime

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class FundingCollector:
    def get_funding(
        self,
        symbol,
    ):
        url = "https://fapi.binance.com/fapi/v1/fundingRate"

        last_error = None

        for attempt in range(3):
            try:
                response = requests.get(
                    url,
                    params={
                        "symbol": symbol,
                        "limit": 1,
                    },
                    timeout=20,
                )
                response.raise_for_status()

                payload = response.json()
                rows = payload.get("result", {}).get("list") if isinstance(payload, dict) else payload
                if not rows:
                    return None

                item = rows[0]
                if isinstance(item, dict):
                    funding_rate = item.get("fundingRate")
                    funding_time = item.get("fundingTime")
                else:
                    if len(item) < 2:
                        return None
                    funding_rate = item[0]
                    funding_time = item[1]

                if funding_rate is None or funding_time is None:
                    return None

                return {
                    "symbol": symbol,
                    "rate": float(funding_rate),
                    "time": datetime.fromtimestamp(int(funding_time) / 1000),
                }
            except Exception as ex:
                last_error = ex
                time.sleep(3)

        if last_error is not None:
            if not is_transient_network_error(last_error):
                print(f"Funding error {symbol}: {classify_network_error(last_error)}")

        return None
