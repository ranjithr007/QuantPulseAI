class OrderFlowScoreEngine:

    def calculate(self, flow):

        if flow is None:
            return 0

        score = 50

        # ----------------
        # Delta
        # ----------------

        if flow.delta > 0:
            score += 15

        else:
            score -= 15

        # ----------------
        # CVD
        # ----------------

        if flow.cumulative_delta > 0:
            score += 15

        else:
            score -= 15

        # ----------------
        # Pressure
        # ----------------

        if flow.buy_pressure > 60:

            score += 15

        elif flow.buy_pressure < 40:

            score -= 15

        # ----------------
        # Whales
        # ----------------

        if flow.whale_buy_count > flow.whale_sell_count:

            score += 15

        elif flow.whale_sell_count > flow.whale_buy_count:

            score -= 15

        # ----------------
        # Absorption
        # ----------------

        if flow.absorption_type == "BUY_ABSORPTION":

            score += 10

        if flow.absorption_type == "SELL_ABSORPTION":

            score -= 10

        # ----------------
        # Exhaustion
        # ----------------

        if flow.exhaustion_type == "BUYER_EXHAUSTION":

            score -= 10

        if flow.exhaustion_type == "SELLER_EXHAUSTION":

            score += 10

        return max(0, min(score, 100))