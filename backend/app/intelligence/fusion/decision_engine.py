class DecisionEngine:

    def decide(self, confidence):

        if confidence >= 75:

            return "STRONG_LONG"

        elif confidence >= 60:

            return "LONG"

        elif confidence <= 25:

            return "STRONG_SHORT"

        elif confidence <= 40:

            return "SHORT"

        return "WAIT"
