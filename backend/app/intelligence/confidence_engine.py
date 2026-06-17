class ConfidenceEngine:
    def combine(self, *scores):
        values = [float(score) for score in scores if score is not None]

        if not values:
            return 0

        return round(sum(values) / len(values), 2)
