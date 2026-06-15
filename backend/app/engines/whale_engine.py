from datetime import datetime, timedelta

from app.database.models.whale_trades import WhaleTrade


class WhaleEngine:

    def analyze(self, db, symbol):

        since = datetime.now() - timedelta(minutes=15)

        trades = (
            db.query(WhaleTrade)
            .filter(WhaleTrade.symbol == symbol, WhaleTrade.trade_time >= since)
            .all()
        )

        buy_volume = 0

        sell_volume = 0

        for trade in trades:

            if trade.side == "BUY":

                buy_volume += trade.value_usd

            else:

                sell_volume += trade.value_usd

        net = buy_volume - sell_volume

        total = buy_volume + sell_volume

        if total == 0:

            score = 0

        else:

            score = (net / total) * 100

        if score > 30:

            bias = "ACCUMULATION"

        elif score < -30:

            bias = "DISTRIBUTION"

        else:

            bias = "NEUTRAL"

        return {
            "symbol": symbol,
            "buy_volume": round(buy_volume, 2),
            "sell_volume": round(sell_volume, 2),
            "net_flow": round(net, 2),
            "whale_score": round(score, 2),
            "bias": bias,
            "confidence": abs(round(score, 2)),
        }