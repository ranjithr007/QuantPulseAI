from datetime import datetime

from sqlalchemy import inspect

from app.database.models.funding_rates import FundingRate
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.paper_trading.exit_policy import PAPER_EXIT_MONITOR_TIMEFRAME
from app.paper_trading.exit_policy import PAPER_TARGET1_FRACTION
from app.paper_trading.exit_policy import build_policy_trade_levels
from app.paper_trading.exit_policy import target1_protection_stop
from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.repositories._db_utils import commit_or_rollback, flush_or_rollback


class StrategyShadowTradeRepository:
    """Isolated forward-test ledger; it never consumes official paper capital."""

    def ensure_table(self, db):
        if not USING_SQLITE_FALLBACK:
            return
        engine = db.get_bind()
        StrategyShadowTrade.__table__.create(bind=engine, checkfirst=True)
        # ``create(checkfirst=True)`` is intentionally idempotent. Inspecting
        # here also forces a clear failure when a legacy fallback schema is
        # missing the governed table rather than silently mixing ledgers.
        if StrategyShadowTrade.__tablename__ not in inspect(engine).get_table_names():
            raise RuntimeError("Strategy shadow ledger could not be initialized")

    def get_open_trades(self, db):
        self.ensure_table(db)
        return (
            db.query(StrategyShadowTrade)
            .filter(StrategyShadowTrade.status == "OPEN")
            .all()
        )

    def all_trades(self, db, *, strategy_id=None, strategy_version=None):
        self.ensure_table(db)
        query = db.query(StrategyShadowTrade)
        if strategy_id:
            query = query.filter(StrategyShadowTrade.strategy_id == strategy_id)
        if strategy_version:
            query = query.filter(
                StrategyShadowTrade.strategy_version == strategy_version
            )
        return query.all()

    def has_open_trade(self, db, strategy_id, strategy_version, symbol):
        self.ensure_table(db)
        return (
            db.query(StrategyShadowTrade)
            .filter(StrategyShadowTrade.strategy_id == strategy_id)
            .filter(StrategyShadowTrade.strategy_version == strategy_version)
            .filter(StrategyShadowTrade.symbol == str(symbol).upper())
            .filter(StrategyShadowTrade.status == "OPEN")
            .first()
            is not None
        )

    def has_trade_for_plan(self, db, trade_plan_id):
        self.ensure_table(db)
        return (
            db.query(StrategyShadowTrade)
            .filter(StrategyShadowTrade.trade_plan_id == trade_plan_id)
            .first()
            is not None
        )

    def save_candidate(self, db, candidate):
        self.ensure_table(db)
        plan = candidate["trade_plan"]
        authorization = candidate["risk_decision"]
        risk = candidate.get("execution_risk") or authorization
        fill = candidate.get("fill_profile") or {}
        entry = float(fill.get("entry_fill_price") or plan["entry_price"])
        fee_bps = float(fill.get("fee_bps") or 7.5)
        levels = build_policy_trade_levels(
            candidate["side"],
            entry,
            symbol=candidate["symbol"],
            timeframe=plan.get("entry_timeframe"),
            confidence=risk.get("confidence") or plan.get("confidence") or 0,
            fee_bps=fee_bps,
            price_precision=_price_precision(entry),
        )
        if levels is None:
            raise ValueError("No governed shadow exit policy is available")
        sizing = candidate.get("paper_sizing") or build_inr_paper_sizing(
            risk.get("confidence") or plan.get("confidence") or 0,
            fee_bps=fee_bps,
        )
        opened_at = datetime.utcnow()
        trade = StrategyShadowTrade(
            trade_plan_id=plan["id"],
            risk_decision_id=authorization["id"],
            symbol=str(candidate["symbol"]).upper(),
            side=candidate["side"],
            strategy_id=plan["strategy_id"],
            strategy_version=plan["strategy_version"],
            strategy_decision_snapshot_id=plan["strategy_decision_snapshot_id"],
            entry_price=entry,
            stop_loss=levels["stop_loss"],
            initial_stop_loss=levels["stop_loss"],
            target1=levels["target1"],
            target2=levels["target2"],
            position_size=risk.get("position_size"),
            position_notional_inr=sizing["position_notional_inr"],
            margin_used_inr=sizing["margin_used_inr"],
            leverage=sizing["leverage"],
            risk_reward=levels["target2_net_risk_reward"],
            risk_percent=risk.get("risk_percent"),
            confidence=risk.get("confidence"),
            entry_timeframe=plan.get("entry_timeframe"),
            timeframe_stack=plan.get("timeframe_stack"),
            regime=plan.get("regime"),
            exit_policy=levels["name"],
            target1_fraction=levels["target1_fraction"],
            remaining_position_fraction=1.0,
            max_hold_hours=levels["max_hold_hours"],
            partial_realized_pnl_inr=0.0,
            exit_monitor_timeframe=PAPER_EXIT_MONITOR_TIMEFRAME,
            last_exit_evaluated_at=opened_at,
            validation_contract_version=candidate.get(
                "validation_contract_version"
            ),
            fill_model_version=fill.get("model"),
            planned_entry_price=fill.get(
                "planned_entry_price",
                plan.get("entry_price"),
            ),
            entry_slippage_percent=fill.get("entry_slippage_pct"),
            funding_rate_snapshot=(candidate.get("market_context") or {}).get(
                "fundingRate"
            ),
            fee_bps=fee_bps,
            status="OPEN",
            opened_at=opened_at,
        )
        db.add(trade)
        flush_or_rollback(db)
        commit_or_rollback(db)
        db.refresh(trade)
        return trade

    def apply_target1(self, db, trade, exit_price, candle_time=None, evaluated_at=None):
        fraction = float(
            trade.target1_fraction
            if trade.target1_fraction is not None
            else PAPER_TARGET1_FRACTION
        )
        trade.target1_fraction = fraction
        trade.remaining_position_fraction = max(0.0, 1.0 - fraction)
        trade.target1_hit_at = candle_time or datetime.utcnow()
        trade.target1_exit_price = float(exit_price)
        trade.stop_loss = target1_protection_stop(
            trade.side,
            trade.entry_price,
            trade.target1,
            _price_precision(trade.entry_price),
        )
        contribution = (
            _directional_pnl_percent(trade.side, trade.entry_price, exit_price)
            - (float(trade.fee_bps or 0) * 2 / 100)
        ) * fraction
        trade.partial_realized_pnl_inr = round(
            float(trade.position_notional_inr or 0) * contribution / 100,
            2,
        )
        if evaluated_at is not None:
            trade.last_exit_evaluated_at = evaluated_at
        commit_or_rollback(db)
        db.refresh(trade)
        return trade

    def move_stop_loss(self, db, trade, stop_loss, evaluated_at=None):
        requested = float(stop_loss)
        current = float(trade.stop_loss)
        improves = requested > current if trade.side == "LONG" else requested < current
        if improves:
            trade.stop_loss = requested
            if evaluated_at is not None:
                trade.last_exit_evaluated_at = evaluated_at
            commit_or_rollback(db)
            db.refresh(trade)
        return trade

    def mark_exit_evaluated(self, db, trade, evaluated_at):
        trade.last_exit_evaluated_at = evaluated_at
        commit_or_rollback(db)
        db.refresh(trade)
        return trade

    def close_trade(self, db, trade, exit_price, result, fill_profile=None):
        closed_at = datetime.utcnow()
        trade.status = "CLOSED"
        trade.exit_price = float(exit_price)
        trade.exit_reason = str(
            (fill_profile or {}).get("trigger_type") or result or "EXIT"
        ).upper()
        trade.exit_slippage_percent = (fill_profile or {}).get(
            "exit_slippage_pct"
        )
        gross = _gross_pnl_percent(trade, exit_price)
        fees = float(trade.fee_bps or 0) * 2 / 100
        funding = _funding_cost_percent(db, trade, closed_at)
        trade.gross_pnl_percent = round(gross, 4)
        trade.fees_percent = round(fees, 4)
        trade.funding_event_count = funding["event_count"]
        trade.funding_cost_percent = round(funding["percent"], 6)
        trade.pnl_percent = round(gross - fees - funding["percent"], 4)
        trade.realized_pnl_inr = round(
            float(trade.position_notional_inr or 0) * trade.pnl_percent / 100,
            2,
        )
        trade.result = str(result).upper()
        if trade.result == "TIME_EXIT":
            trade.result = "WIN" if trade.pnl_percent > 0 else "LOSS"
        trade.closed_at = closed_at
        commit_or_rollback(db)
        db.refresh(trade)
        return trade


def _gross_pnl_percent(trade, exit_price):
    def leg(price):
        return _directional_pnl_percent(
            trade.side,
            trade.entry_price,
            price,
        )

    if trade.target1_exit_price is None:
        return leg(exit_price)
    fraction = float(trade.target1_fraction or PAPER_TARGET1_FRACTION)
    remaining = float(
        trade.remaining_position_fraction
        if trade.remaining_position_fraction is not None
        else 1.0 - fraction
    )
    return leg(trade.target1_exit_price) * fraction + leg(exit_price) * remaining


def _funding_cost_percent(db, trade, closed_at):
    rows = (
        db.query(FundingRate)
        .filter(FundingRate.symbol == trade.symbol)
        .filter(FundingRate.funding_time > trade.opened_at)
        .filter(FundingRate.funding_time <= closed_at)
        .order_by(FundingRate.funding_time.asc(), FundingRate.id.asc())
        .all()
    )
    events = {
        row.funding_time: float(row.rate)
        for row in rows
        if row.funding_time is not None and row.rate is not None
    }
    direction = 1 if trade.side == "LONG" else -1
    remaining = float(trade.remaining_position_fraction or 1.0)
    value = sum(
        rate
        * 100
        * direction
        * (
            remaining
            if trade.target1_hit_at and event_time > trade.target1_hit_at
            else 1.0
        )
        for event_time, rate in events.items()
    )
    return {"event_count": len(events), "percent": value}


def _directional_pnl_percent(side, entry, exit_price):
    entry = float(entry)
    exit_price = float(exit_price)
    if str(side).upper() == "LONG":
        return (exit_price - entry) / entry * 100
    return (entry - exit_price) / entry * 100


def _price_precision(price):
    price = float(price)
    if price < 1:
        return 6
    if price < 10:
        return 5
    if price < 100:
        return 4
    return 2
