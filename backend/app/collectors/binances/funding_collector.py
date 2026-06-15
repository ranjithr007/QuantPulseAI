import requests
from datetime import datetime


class FundingCollector:


    def get_funding(
        self,
        symbol
    ):


        url=(
        "https://fapi.binance.com/fapi/v1/fundingRate"
        )


        response=requests.get(
            url,
            params={
                "symbol":symbol,
                "limit":1
            }
        )


        item=response.json()[0]


        return {

            "symbol":symbol,


            "rate":float(
                item["fundingRate"]
            ),


            "time":
            datetime.fromtimestamp(
                item["fundingTime"]/1000
            )
        }