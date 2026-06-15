class ReasoningEngine:

    def explain(self, data):

        reasons = []

        if data.ml_score > 70:

            reasons.append("ML models confirm direction")

        if data.regime_score > 70:

            reasons.append("Market regime supports trade")

        if data.orderflow_score > 70:

            reasons.append("Orderflow confirms buyers")

        if data.smc_score > 70:

            reasons.append("Smart money structure detected")

        return reasons
