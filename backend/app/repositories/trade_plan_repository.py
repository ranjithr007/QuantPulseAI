from datetime import datetime

from app.database.models.trade_plan import TradePlan
from app.repositories._db_utils import commit_or_rollback
from app.repositories._db_utils import flush_or_rollback
from app.repositories.trade_thesis_repository import TradeThesisRepository
from app.strategies.registry import LEGACY_UNATTRIBUTED_STRATEGY_ID
from app.strategies.registry import LEGACY_UNATTRIBUTED_STRATEGY_VERSION


class TradePlanRepository:
    def get_open_trades(self, db):
        return db.query(TradePlan).filter(TradePlan.status == "OPEN").all()

    def get_open_trade(self, db, symbol, side=None):
        """Get the symbol's open plan; direction is not part of the lock key."""
        return (
            db.query(TradePlan)
            .filter(TradePlan.symbol == str(symbol).upper())
            .filter(TradePlan.status == "OPEN")
            .order_by(TradePlan.created_at.desc())
            .first()
        )

    def invalidate_open_trades_below_confidence(self, db, min_confidence):
        open_trades = self.get_open_trades(db)
        invalidated = []

        for trade in open_trades:
            confidence = trade.confidence
            if confidence is not None and float(confidence) >= float(min_confidence):
                continue

            invalidated.append(
                self.invalidate_trade(
                    db,
                    trade,
                    reason=(
                        f"Trade plan invalidated by confidence gate (<{float(min_confidence):.0f})"
                    ),
                )
            )

        return invalidated

    def has_open_trade(self, db, symbol, side=None):
        return self.get_open_trade(db, symbol, side) is not None

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

        if getattr(trade, "thesis_id", None):
            TradeThesisRepository().set_lifecycle_state(
                db,
                trade.thesis_id,
                "COMPLETED" if result == "WIN" else "INVALIDATED",
                reason=f"Trade plan closed with result {result}",
                commit=False,
            )

        commit_or_rollback(db)
        return trade

    def invalidate_trade(self, db, trade, reason):
        trade.status = "CLOSED"
        trade.exit_price = trade.entry_price
        trade.result = "INVALIDATED"
        trade.pnl_percent = 0.0
        trade.closed_at = datetime.utcnow()

        if getattr(trade, "thesis_id", None):
            TradeThesisRepository().set_lifecycle_state(
                db,
                trade.thesis_id,
                "INVALIDATED",
                reason=reason,
                commit=False,
            )

        commit_or_rollback(db)
        return trade

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
            data_generation_id=plan.get("data_generation_id"),
            strategy_id=(
                plan.get("strategy_id") or LEGACY_UNATTRIBUTED_STRATEGY_ID
            ),
            strategy_version=(
                plan.get("strategy_version")
                or LEGACY_UNATTRIBUTED_STRATEGY_VERSION
            ),
            strategy_decision_snapshot_id=plan.get(
                "strategy_decision_snapshot_id"
            ),
            exit_policy=plan.get("exit_policy"),
            target1_fraction=plan.get("target1_fraction"),
            max_hold_hours=plan.get("max_hold_hours"),
            status="OPEN",
        )

        db.add(trade)
        flush_or_rollback(db)
        thesis = TradeThesisRepository().create_for_trade_plan(
            db,
            trade,
            scenario=plan.get("scenario"),
            contradiction=plan.get("contradiction"),
            commit=False,
        )
        trade.thesis_id = thesis.id
        commit_or_rollback(db)
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
            data_generation_id=context.get("data_generation_id"),
            strategy_id=(
                context.get("strategy_id") or LEGACY_UNATTRIBUTED_STRATEGY_ID
            ),
            strategy_version=(
                context.get("strategy_version")
                or LEGACY_UNATTRIBUTED_STRATEGY_VERSION
            ),
            strategy_decision_snapshot_id=context.get(
                "strategy_decision_snapshot_id"
            ),
            exit_policy=plan.get("exit_policy"),
            target1_fraction=plan.get("target1_fraction"),
            max_hold_hours=plan.get("max_hold_hours"),
            status="OPEN",
        )

        db.add(trade)
        flush_or_rollback(db)
        thesis = TradeThesisRepository().create_for_trade_plan(
            db,
            trade,
            scenario=context.get("scenario"),
            contradiction=context.get("contradiction"),
            commit=False,
        )
        trade.thesis_id = thesis.id
        commit_or_rollback(db)
        db.refresh(trade)
        return trade


def _timeframe_stack_value(value):
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return value
