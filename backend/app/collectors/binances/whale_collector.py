import requests
import time

from datetime import datetime


class WhaleCollector:

    URL = "https://fapi.binance.com/fapi/v1/aggTrades"

   

    def get_order_flow(self, symbol):

        params = {"symbol": symbol, "limit": 1000}

        data = None

        for attempt in range(3):

            try:

                response = requests.get(self.URL, params=params, timeout=10)

                response.raise_for_status()

                data = response.json()

                break

            except Exception as ex:

                print(f"Binance error {symbol}: {ex}")

                time.sleep(3)

        if data is None:
            return None

        buy_volume = 0
        sell_volume = 0

        whale_buy_count = 0
        whale_sell_count = 0

        whale_buy_volume = 0
        whale_sell_volume = 0

        whales = []

        largest_trade_value = 0

        start_price = float(data[0]["p"])

        end_price = float(data[-1]["p"])

        for x in data:

            price = float(x["p"])

            qty = float(x["q"])

            value = price * qty

            if x["m"]:

                side = "SELL"

                sell_volume += qty

            else:

                side = "BUY"

                buy_volume += qty

            if value > largest_trade_value:

                largest_trade_value = value

            # Whale detection

            if value >= 10000:

                if side == "BUY":

                    whale_buy_count += 1

                    whale_buy_volume += qty

                else:

                    whale_sell_count += 1

                    whale_sell_volume += qty

                whales.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "price": price,
                        "quantity": qty,
                        "value_usd": value,
                        "trade_time": datetime.fromtimestamp(x["T"] / 1000),
                    }
                )

        # -----------------
        # DELTA
        # -----------------

        delta = buy_volume - sell_volume      

        total_volume = buy_volume + sell_volume

        if total_volume:

            buy_pressure = (buy_volume / total_volume) * 100

            sell_pressure = (sell_volume / total_volume) * 100

        else:

            buy_pressure = 0
            sell_pressure = 0

        price_change_pct = ((end_price - start_price) / start_price) * 100

        # -----------------
        # Absorption
        # -----------------

        absorption = "NONE"

        absorption_strength = 0

        if delta < 0 and abs(price_change_pct) < 0.05:

            absorption = "BUY_ABSORPTION"

            absorption_strength = abs(delta)

        elif delta > 0 and abs(price_change_pct) < 0.05:

            absorption = "SELL_ABSORPTION"

            absorption_strength = delta

        # -----------------
        # Exhaustion
        # -----------------

        exhaustion = "NONE"

        exhaustion_strength = 0

        # later compare previous CVD snapshots

        # -----------------
        # Score
        # -----------------

        score = 0

        if delta > 0:

            score += 30

        if buy_pressure > 60:

            score += 30

        if whale_buy_count > whale_sell_count:

            score += 30

        if absorption == "NONE":

            score += 10

        return {
            "symbol": symbol,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "delta": delta,
            "buy_pressure": round(buy_pressure, 2),
            "sell_pressure": round(sell_pressure, 2),
            "aggressive_side": "BUYERS" if delta > 0 else "SELLERS",
            "whale_buy_count": whale_buy_count,
            "whale_sell_count": whale_sell_count,
            "whale_buy_volume": whale_buy_volume,
            "whale_sell_volume": whale_sell_volume,
            "largest_trade_value": largest_trade_value,
            "start_price": start_price,
            "end_price": end_price,
            "price_change_pct": price_change_pct,
            "absorption_type": absorption,
            "absorption_strength": absorption_strength,
            "exhaustion_type": exhaustion,
            "exhaustion_strength": exhaustion_strength,
            "orderflow_score": score,
            "whales": whales,
            "created_at": datetime.utcnow(),
        }