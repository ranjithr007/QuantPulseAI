class FusionEngine:

    def analyze(self, data):

        total_score = (
            data.ml_score * 0.25
            + data.regime_score * 0.25
            + data.orderflow_score * 0.20
            + data.smc_score * 0.15
            + data.liquidation_score * 0.10
            + data.whale_score * 0.05
        )

        if total_score >= 60:

            decision = "STRONG_LONG"

        elif total_score >= 40:

            decision = "LONG"

        elif total_score <= -60:

            decision = "STRONG_SHORT"

        elif total_score <= -40:

            decision = "SHORT"

        else:

            decision = "NEUTRAL"

        return {
            "symbol": data.symbol,
            "decision": decision,
            "confidence": abs(total_score),
            # KEEP COMPONENT SCORES
            "ml_score": data.ml_score,
            "regime_score": data.regime_score,
            "orderflow_score": data.orderflow_score,
            "smc_score": data.smc_score,
            "liquidation_score": data.liquidation_score,
            "whale_score": data.whale_score,
        }
