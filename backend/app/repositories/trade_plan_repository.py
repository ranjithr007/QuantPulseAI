from datetime import datetime

from app.database.models.trade_plan import TradePlan


class TradePlanRepository:

    def get_open_trades(self, db):

        return db.query(TradePlan).filter(TradePlan.status == "OPEN").all()

    def has_open_trade(self, db, symbol, side):

        return (
            db.query(TradePlan)
            .filter(TradePlan.symbol == symbol)
            .filter(TradePlan.side == side)
            .filter(TradePlan.status == "OPEN")
            .first()
            is not None
        )

    def close_trade(self, db, trade, price, result):

        trade.status = "CLOSED"

        trade.exit_price = price

        trade.result = result

        if trade.side == "LONG":

            pnl = ((price - trade.entry_price) / trade.entry_price) * 100

        else:

            pnl = ((trade.entry_price - price) / trade.entry_price) * 100

        trade.pnl_percent = round(pnl, 2)

        trade.closed_at = datetime.utcnow()

        db.commit()

        return trade

    # def save_trade(self, db, plan):

    #     trade = TradePlan(
    #         symbol=plan["symbol"],
    #         side=plan["side"],
    #         entry_price=plan["entry"],
    #         stop_loss=plan["stop_loss"],
    #         target1=plan["targets"][0],
    #         target2=plan["targets"][1],
    #         target3=plan["targets"][2],
    #         risk_reward=plan["rr"],
    #         confidence=plan["confidence"],
    #         status="OPEN",
    #     )

    #     db.add(trade)

    #     db.commit()

    #     db.refresh(trade)

    #     return trade

    def save_trade_plan(self, db, plan):

        trade = TradePlan(
            symbol=plan["symbol"],
            side=plan["side"],
            entry_price=plan["entry"],
            stop_loss=plan["stop_loss"],
            target1=plan["targets"][0],
            target2=plan["targets"][1],
            target3=plan["targets"][2],
            risk_reward=plan["rr"],
            confidence=plan["confidence"],
            mode=plan.get("mode"),
            entry_timeframe=plan.get("entry_timeframe"),
            timeframe_stack=_timeframe_stack_value(plan.get("timeframe_stack")),
            regime=plan.get("regime"),
            status="OPEN",
        )

        db.add(trade)

        db.commit()

        db.refresh(trade)

        return trade

    def save_ready_trade_plan(self, db, symbol, side, plan, confidence=0, context=None):

        context = context or {}

        trade = TradePlan(
            symbol=symbol,
            side=side,
            entry_price=plan["entry"],
            stop_loss=plan["stop_loss"],
            target1=plan["target1"],
            target2=plan.get("target2"),
            target3=None,
            risk_reward=plan["risk_reward"],
            confidence=confidence,
            mode=context.get("mode"),
            entry_timeframe=context.get("entry_timeframe"),
            timeframe_stack=_timeframe_stack_value(context.get("timeframe_stack")),
            regime=context.get("regime"),
            status="OPEN",
        )

        db.add(trade)

        db.commit()

        db.refresh(trade)

        return trade


def _timeframe_stack_value(value):
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return value
