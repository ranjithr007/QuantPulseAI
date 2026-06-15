class WeightEngine:

    WEIGHTS = {
        "ml": 0.30,
        "regime": 0.20,
        "orderflow": 0.20,
        "smc": 0.15,
        "liquidation": 0.10,
        "whales": 0.05,
    }

    def calculate(self, data):

        score = (
            data.ml_score * self.WEIGHTS["ml"]
            + data.regime_score * self.WEIGHTS["regime"]
            + data.orderflow_score * self.WEIGHTS["orderflow"]
            + data.smc_score * self.WEIGHTS["smc"]
            + data.liquidation_score * self.WEIGHTS["liquidation"]
            + data.whale_score * self.WEIGHTS["whales"]
        )

        return round(score, 2)
