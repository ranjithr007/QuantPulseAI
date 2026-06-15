class SmartMoneyFusionEngine:

    def analyze(self, smc, orderflow):

        score = 50

        bias = "NEUTRAL"

        reasons = []

        if smc is None or orderflow is None:

            return {"bias": bias, "score": score, "reasons": reasons}

        # =========================
        # Smart Money LONG trap
        # =========================

        if (
            smc.liquidity_sweep == "SELL_SIDE_SWEEP"
            and orderflow.absorption_type == "BUY_ABSORPTION"
            and orderflow.cumulative_delta > 0
        ):

            score += 40

            bias = "SMART_MONEY_LONG"

            reasons.append("Sell sweep + buy absorption + CVD rising")

        # =========================
        # Smart Money SHORT trap
        # =========================

        if (
            smc.liquidity_sweep == "BUY_SIDE_SWEEP"
            and orderflow.absorption_type == "SELL_ABSORPTION"
            and orderflow.cumulative_delta < 0
        ):

            score -= 40

            bias = "SMART_MONEY_SHORT"

            reasons.append("Buy sweep + sell absorption + CVD falling")

        # =========================
        # Trend continuation LONG
        # =========================

        if (
            smc.bos == "BULLISH_BOS"
            and orderflow.delta > 0
            and orderflow.whale_buy_count > orderflow.whale_sell_count
        ):

            score += 25

            reasons.append("BOS confirmed by whale buying")

        # =========================
        # Trend continuation SHORT
        # =========================

        if (
            smc.bos == "BEARISH_BOS"
            and orderflow.delta < 0
            and orderflow.whale_sell_count > orderflow.whale_buy_count
        ):

            score -= 25

            reasons.append("Bearish BOS confirmed by whales")

        return {"bias": bias, "score": max(0, min(score, 100)), "reasons": reasons}