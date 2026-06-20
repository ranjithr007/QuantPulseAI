class ConfidenceEngine:
    def combine(self, *scores):
        values = [float(score) for score in scores if score is not None]

        if not values:
            return 0

        return round(sum(values) / len(values), 2)

    def decay(self, age_seconds, half_life_seconds=900, floor=0.15):
        if age_seconds is None:
            return floor

        try:
            age = max(0.0, float(age_seconds))
            half_life = max(1.0, float(half_life_seconds))
            base = 0.5 ** (age / half_life)
            return round(max(floor, base), 4)
        except (TypeError, ValueError):
            return floor

    def bayesian_update(self, prior, likelihood):
        prior = self._bound_probability(prior)
        likelihood = self._bound_probability(likelihood)

        numerator = prior * likelihood
        denominator = numerator + (1 - prior) * (1 - likelihood)

        if denominator <= 0:
            return round(prior, 4)

        return round(numerator / denominator, 4)

    def normalize(self, values):
        total = sum(max(0.0, float(value)) for value in values.values())

        if total <= 0:
            return {name: 0 for name in values}

        return {
            name: round((max(0.0, float(value)) / total) * 100, 2)
            for name, value in values.items()
        }

    @staticmethod
    def _bound_probability(value):
        try:
            return min(0.99, max(0.01, float(value)))
        except (TypeError, ValueError):
            return 0.5
