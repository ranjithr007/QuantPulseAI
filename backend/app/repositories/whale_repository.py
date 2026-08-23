from app.database.models.whale_trades import WhaleTrade
from app.repositories._db_utils import commit_or_rollback


class WhaleRepository:

    def save_many(self, db, trades):
        trades = list(trades or [])
        if not trades:
            return 0
        normalized = []
        for trade in trades:
            exchange_trade_id = trade.get("exchange_trade_id")
            normalized.append(
                {
                    **trade,
                    "venue": str(trade.get("venue") or "BINANCE").upper(),
                    "symbol": str(trade["symbol"]).upper(),
                    "exchange_trade_id": (
                        str(exchange_trade_id)
                        if exchange_trade_id is not None
                        else None
                    ),
                }
            )
        identities = {
            item["exchange_trade_id"]
            for item in normalized
            if item["exchange_trade_id"] is not None
        }
        first = normalized[0]
        existing_ids = set()
        if identities:
            existing_ids = {
                row[0]
                for row in (
                    db.query(WhaleTrade.exchange_trade_id)
                    .filter(
                        WhaleTrade.venue == first["venue"],
                        WhaleTrade.symbol == first["symbol"],
                        WhaleTrade.exchange_trade_id.in_(identities),
                    )
                    .all()
                )
            }
        inserted = 0
        seen = set(existing_ids)
        for item in normalized:
            identity = item["exchange_trade_id"]
            if identity is not None and identity in seen:
                continue
            db.add(WhaleTrade(**item))
            if identity is not None:
                seen.add(identity)
            inserted += 1
        commit_or_rollback(db)
        return inserted

    def save(self, db, trade):
        venue = str(trade.get("venue") or "BINANCE").upper()
        exchange_trade_id = trade.get("exchange_trade_id")
        if exchange_trade_id is not None:
            existing = (
                db.query(WhaleTrade)
                .filter(
                    WhaleTrade.venue == venue,
                    WhaleTrade.symbol == str(trade["symbol"]).upper(),
                    WhaleTrade.exchange_trade_id == str(exchange_trade_id),
                )
                .first()
            )
            if existing is not None:
                return existing

        entity = WhaleTrade(
            **{
                **trade,
                "venue": venue,
                "exchange_trade_id": (
                    str(exchange_trade_id) if exchange_trade_id is not None else None
                ),
                "symbol": str(trade["symbol"]).upper(),
            }
        )
        db.add(entity)

        commit_or_rollback(db)
        return entity
