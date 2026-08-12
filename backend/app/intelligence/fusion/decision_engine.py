class DecisionEngine:

    def decide(self, score):

        if score >= 60:

            return "STRONG_LONG"

        elif score >= 40:

            return "LONG"

        elif score <= -60:

            return "STRONG_SHORT"

        elif score <= -40:

            return "SHORT"

        return "WAIT"
