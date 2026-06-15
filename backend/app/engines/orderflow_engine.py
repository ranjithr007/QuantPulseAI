class OrderFlowEngine:

    def detect_exhaustion(self, current, history):

        if len(history) < 3:

            return ("NONE", 0)

        old_cvd = history[-1].cumulative_delta

        recent_cvd = history[0].cumulative_delta

        cvd_change = recent_cvd - old_cvd

        # price rising
        # CVD falling

        if current["price_change_pct"] > 0 and cvd_change < 0:

            return ("BUYER_EXHAUSTION", abs(cvd_change))

        # price falling
        # CVD rising

        if current["price_change_pct"] < 0 and cvd_change > 0:

            return ("SELLER_EXHAUSTION", abs(cvd_change))

        return ("NONE", 0)

    def detect_absorption(self, flow):

        delta = flow["delta"]

        price_move = abs(flow["price_change_pct"])

        # sellers attack
        # price does not fall

        if delta < 0 and price_move < 0.05:

            return ("BUY_ABSORPTION", abs(delta))

        # buyers attack
        # price cannot rise

        if delta > 0 and price_move < 0.05:

            return ("SELL_ABSORPTION", delta)

        return ("NONE", 0)