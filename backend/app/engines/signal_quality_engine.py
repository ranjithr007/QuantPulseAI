class SignalQualityEngine:

    def analyze(self, signal):

        score = signal.confidence

        risk = 100 - score

        reasons = []

        trade = False

        grade = "C"

        if score >= 80:

            grade = "A"

            trade = True

            reasons.append("High probability setup")

        elif score >= 60:

            grade = "B"

            trade = True

            reasons.append("Acceptable setup")

        else:

            grade = "C"

            trade = False

            reasons.append("Low confidence ignored")

        if signal.signal == "WAIT":

            trade = False

            reasons.append("No direction")

        return {
            "symbol": signal.symbol,
            "signal": signal.signal,
            "quality_grade": grade,
            "confidence": score,
            "risk_score": risk,
            "trade_allowed": trade,
            "reason": ",".join(reasons),
        }