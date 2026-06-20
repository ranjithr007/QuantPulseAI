from datetime import datetime

from app.database.models.paper_trade import PaperTrade


class PaperTradeRepository:
    def ensure_table(self, db):
        PaperTrade.__table__.create(bind=db.get_bind(), checkfirst=True)

    def get_open_trades(self, db):
        self.ensure_table(db)

        return db.query(PaperTrade).filter(PaperTrade.status == "OPEN").all()

    def list_trades(self, db, status=None, symbol=None, limit=50):
        self.ensure_table(db)
        query = db.query(PaperTrade)

        if status:
            query = query.filter(PaperTrade.status == status)

        if symbol:
            query = query.filter(PaperTrade.symbol == symbol)

        return (
            query.order_by(PaperTrade.created_at.desc())
            .limit(limit)
            .all()
        )

    def all_trades(self, db, symbol=None):
        self.ensure_table(db)
        query = db.query(PaperTrade)

        if symbol:
            query = query.filter(PaperTrade.symbol == symbol)

        return query.all()

    def has_open_trade(self, db, symbol, side):
        self.ensure_table(db)

        return (
            db.query(PaperTrade)
            .filter(PaperTrade.symbol == symbol)
            .filter(PaperTrade.side == side)
            .filter(PaperTrade.status == "OPEN")
            .first()
            is not None
        )

    def save_candidate(self, db, candidate):
        self.ensure_table(db)
        trade_plan = candidate["trade_plan"]
        risk = candidate["risk_decision"]
        fill_profile = candidate.get("fill_profile") or {}
        entry_price = fill_profile.get("entry_fill_price", trade_plan["entry_price"])
        risk_reward = fill_profile.get("effective_risk_reward", risk["risk_reward"])
        paper_trade = PaperTrade(
            trade_plan_id=trade_plan["id"],
            risk_decision_id=risk["id"],
            symbol=candidate["symbol"],
            side=candidate["side"],
            entry_price=entry_price,
            stop_loss=trade_plan["stop_loss"],
            target1=trade_plan["target1"],
            target2=trade_plan["target2"],
            position_size=risk["position_size"],
            risk_reward=risk_reward,
            risk_percent=risk["risk_percent"],
            confidence=risk["confidence"],
            status="OPEN",
        )

        db.add(paper_trade)
        db.commit()
        db.refresh(paper_trade)

        return paper_trade

    def close_trade(self, db, trade, exit_price, result):
        trade.status = "CLOSED"
        trade.exit_price = exit_price
        trade.result = result

        if trade.side == "LONG":
            pnl = ((exit_price - trade.entry_price) / trade.entry_price) * 100
        else:
            pnl = ((trade.entry_price - exit_price) / trade.entry_price) * 100

        trade.pnl_percent = round(pnl, 2)
        trade.closed_at = datetime.utcnow()

        db.commit()
        db.refresh(trade)

        return trade
