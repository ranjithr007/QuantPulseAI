class SmartMoneyEngine:

    def analyze(self, liquidity, heatmap):

        direction = "WAIT"

        confidence = 0

        reasons = []

        # Long liquidation hunt

        if liquidity.long_squeeze_probability > 60 and heatmap.bias == "LONG_LIQUIDATIONS":

            direction = "SHORT"

            confidence += 70 * min(100, max(0, float(heatmap.confidence or 0))) / 100

            reasons.append("Observed long liquidations with long-squeeze risk")

        # Short liquidation hunt

        elif liquidity.short_squeeze_probability > 60 and heatmap.bias == "SHORT_LIQUIDATIONS":

            direction = "LONG"

            confidence += 70 * min(100, max(0, float(heatmap.confidence or 0))) / 100

            reasons.append("Observed short liquidations with short-squeeze risk")

        return {
            "direction": direction,
            "confidence": confidence,
            "reason": ",".join(reasons),
        }
