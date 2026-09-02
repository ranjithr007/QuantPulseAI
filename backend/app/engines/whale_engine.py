from datetime import datetime, timedelta

from sqlalchemy import case, func

from app.database.models.whale_trades import WhaleTrade


class WhaleEngine:

    def analyze(self, db, symbol):

        since = datetime.now() - timedelta(minutes=15)

        buy_volume, sell_volume = (
            db.query(
                func.coalesce(
                    func.sum(
                        case(
                            (WhaleTrade.side == "BUY", WhaleTrade.value_usd),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (WhaleTrade.side == "SELL", WhaleTrade.value_usd),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
            )
            .filter(WhaleTrade.symbol == symbol, WhaleTrade.trade_time >= since)
            .one()
        )
        buy_volume = float(buy_volume or 0.0)
        sell_volume = float(sell_volume or 0.0)

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
