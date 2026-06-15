import numpy as np


class EnsembleEngine:

    def predict(self, features, models):

        predictions = []

        for model in models:

            prob = model.predict(features)

            predictions.append(prob[0][1])

        confidence = np.mean(predictions)

        return {
            "long_probability": round(confidence * 100, 2),
            "short_probability": round((1 - confidence) * 100, 2),
        }