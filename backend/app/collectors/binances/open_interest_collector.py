import requests
from datetime import datetime


class OpenInterestCollector:


    def get_data(
        self,
        symbol
    ):


        url=(
        "https://fapi.binance.com/fapi/v1/openInterest"
        )


        r=requests.get(
            url,
            params={
                "symbol":symbol
            }
        )


        data=r.json()


        return {

            "symbol":symbol,

            "value":float(
                data["openInterest"]
            ),

            "time":datetime.now()

        }