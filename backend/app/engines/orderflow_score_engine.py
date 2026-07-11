class OrderFlowScoreEngine:

    def calculate(self, flow):

        if flow is None:
            return 0

        score = 50

        delta = self._value(flow, "delta", "Delta")
        cumulative_delta = self._value(flow, "cumulative_delta", "CVD")
        buy_pressure = self._value(flow, "buy_pressure", "BuyerStrength")
        whale_buy_count = self._value(flow, "whale_buy_count", "BuyerStrength")
        whale_sell_count = self._value(flow, "whale_sell_count", "SellerStrength")
        absorption_type = self._value(flow, "absorption_type", "Absorption")
        exhaustion_type = self._value(flow, "exhaustion_type", "Exhaustion")

        # ----------------
        # Delta
        # ----------------

        if self._number(delta) > 0:
            score += 15

        else:
            score -= 15

        # ----------------
        # CVD
        # ----------------

        if self._number(cumulative_delta) > 0:
            score += 15

        else:
            score -= 15

        # ----------------
        # Pressure
        # ----------------

        if self._number(buy_pressure) > 60:

            score += 15

        elif self._number(buy_pressure) < 40:

            score -= 15

        # ----------------
        # Whales
        # ----------------

        if self._number(whale_buy_count) > self._number(whale_sell_count):

            score += 15

        elif self._number(whale_sell_count) > self._number(whale_buy_count):

            score -= 15

        # ----------------
        # Absorption
        # ----------------

        if absorption_type == "BUY_ABSORPTION":

            score += 10

        if absorption_type == "SELL_ABSORPTION":

            score -= 10

        # ----------------
        # Exhaustion
        # ----------------

        if exhaustion_type == "BUYER_EXHAUSTION":

            score -= 10

        if exhaustion_type == "SELLER_EXHAUSTION":

            score += 10

        return max(0, min(score, 100))

    def _value(self, item, *names):
        for name in names:
            if hasattr(item, name):
                value = getattr(item, name)
                if value is not None:
                    return value

        return None

    def _number(self, value):
        if value is None:
            return 0

        try:
            return float(value)
        except (TypeError, ValueError):
            return 0
