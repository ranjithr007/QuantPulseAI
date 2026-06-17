class SentimentEngine:
    def analyze(self, fear_greed_score=None, news_score=None, social_score=None):
        values = [
            value
            for value in [fear_greed_score, news_score, social_score]
            if value is not None
        ]

        if not values:
            return {
                "sentiment": "UNKNOWN",
                "sentiment_score": 50,
                "reason": "No sentiment inputs supplied",
            }

        score = sum(values) / len(values)

        if score >= 65:
            sentiment = "BULLISH"
        elif score <= 35:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        return {
            "sentiment": sentiment,
            "sentiment_score": round(score, 2),
            "input_count": len(values),
        }
