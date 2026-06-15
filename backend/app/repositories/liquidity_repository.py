from app.database.models.liquidity_signals import LiquiditySignal


class LiquidityRepository:

    def save(self, db, result):

        signal = "NEUTRAL"

        if result["long_squeeze_probability"] > 70:

            signal = "LONG_SQUEEZE"

        elif result["short_squeeze_probability"] > 70:

            signal = "SHORT_SQUEEZE"

        db.add(
            LiquiditySignal(
                symbol=result["symbol"],
                signal=signal,
                long_squeeze_probability=result["long_squeeze_probability"],
                short_squeeze_probability=result["short_squeeze_probability"],
                confidence=result["confidence"],
            )
        )

        db.commit()