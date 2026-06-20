class SmartMoneyFusionEngine:

    def analyze(self, smc, orderflow):

        score = 50

        bias = "NEUTRAL"

        reasons = []

        if smc is None or orderflow is None:

            return {"bias": bias, "score": score, "reasons": reasons}

        bos_type = self._value(smc, "bos", "bos_type")
        liquidity_sweep = self._value(smc, "liquidity_sweep")
        absorption_type = self._value(orderflow, "absorption_type", "Absorption")
        delta = self._value(orderflow, "delta", "Delta", "cumulative_delta", "CVD")
        whale_buy_count = self._value(orderflow, "whale_buy_count", "BuyerStrength")
        whale_sell_count = self._value(orderflow, "whale_sell_count", "SellerStrength")

        # =========================
        # Smart Money LONG trap
        # =========================

        if (
            self._matches(liquidity_sweep, "SELL_SIDE_SWEEP")
            and self._matches(absorption_type, "BUY_ABSORPTION")
            and self._number(delta) > 0
        ):

            score += 40

            bias = "SMART_MONEY_LONG"

            reasons.append("Sell sweep + buy absorption + CVD rising")

        # =========================
        # Smart Money SHORT trap
        # =========================

        if (
            self._matches(liquidity_sweep, "BUY_SIDE_SWEEP")
            and self._matches(absorption_type, "SELL_ABSORPTION")
            and self._number(delta) < 0
        ):

            score -= 40

            bias = "SMART_MONEY_SHORT"

            reasons.append("Buy sweep + sell absorption + CVD falling")

        # =========================
        # Trend continuation LONG
        # =========================

        if (
            self._matches(bos_type, "BULLISH_BOS")
            and self._number(delta) > 0
            and self._number(whale_buy_count) > self._number(whale_sell_count)
        ):

            score += 25

            reasons.append("BOS confirmed by whale buying")

        # =========================
        # Trend continuation SHORT
        # =========================

        if (
            self._matches(bos_type, "BEARISH_BOS")
            and self._number(delta) < 0
            and self._number(whale_sell_count) > self._number(whale_buy_count)
        ):

            score -= 25

            reasons.append("Bearish BOS confirmed by whales")

        return {"bias": bias, "score": max(0, min(score, 100)), "reasons": reasons}

    def _value(self, item, *names):
        for name in names:
            if hasattr(item, name):
                value = getattr(item, name)
                if value is not None:
                    return value

        return None

    def _matches(self, value, expected):
        if value is None:
            return False

        return str(value).upper() == expected

    def _number(self, value):
        if value is None:
            return 0

        try:
            return float(value)
        except (TypeError, ValueError):
            return 0
