from app.database.models.market_candles import MarketCandle


class BacktestEngine:

    def test(self, db, signal):

        future = (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol == signal.symbol)
            .filter(MarketCandle.candle_time > signal.created_at)
            .order_by(MarketCandle.candle_time.asc())
            .first()
        )

        if not future:

            return None

        if signal.signal == "LONG":

            pnl = ((future.close_price - signal.entry_price) / signal.entry_price) * 100

        else:

            pnl = ((signal.entry_price - future.close_price) / signal.entry_price) * 100

        return {
            "symbol": signal.symbol,
            "signal": signal.signal,
            "entry_price": signal.entry_price,
            "exit_price": future.close_price,
            "pnl_percent": round(pnl, 2),
            "is_win": pnl > 0,
            "confidence": signal.confidence,
        }