class SmartMoneyEngine:

    def analyze(self, liquidity, heatmap):

        direction = "WAIT"

        confidence = 0

        reasons = []

        # Long liquidation hunt

        if liquidity.long_squeeze_probability > 60 and heatmap.bias == "HUNT_LONGS":

            direction = "SHORT"

            confidence += 70

            reasons.append("Long liquidation hunt detected")

        # Short liquidation hunt

        elif liquidity.short_squeeze_probability > 60 and heatmap.bias == "HUNT_SHORTS":

            direction = "LONG"

            confidence += 70

            reasons.append("Short squeeze setup detected")

        return {
            "direction": direction,
            "confidence": confidence,
            "reason": ",".join(reasons),
        }