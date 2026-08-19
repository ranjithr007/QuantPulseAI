from datetime import datetime

from sqlalchemy import inspect, text

from app.database.models.funding_rates import FundingRate
from app.database.models.paper_trade import PaperTrade
from app.database.models.trade_plan import TradePlan
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.paper_trading.exit_policy import PAPER_STAGED_EXIT_POLICY
from app.paper_trading.exit_policy import PAPER_EXIT_MONITOR_TIMEFRAME
from app.paper_trading.exit_policy import build_policy_trade_levels
from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.repositories._db_utils import commit_or_rollback
from app.repositories._db_utils import flush_or_rollback
from app.repositories.trade_thesis_repository import TradeThesisRepository
from app.repositories.paper_wallet_ledger_repository import PaperWalletLedgerRepository


class PaperTradeRepository:
    ACCOUNT_EXECUTION_LOCK_KEY = 715_202_608_150_001

    def acquire_account_execution_lock(self, db):
        """Serialize account-wide paper capacity checks within one transaction."""
        dialect = str(db.get_bind().dialect.name).lower()
        if dialect == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": self.ACCOUNT_EXECUTION_LOCK_KEY},
            )
        elif dialect == "mssql":
            result = db.execute(
                text(
                    "DECLARE @result int; "
                    "EXEC @result = sp_getapplock "
                    "@Resource = :resource, @LockMode = 'Exclusive', "
                    "@LockOwner = 'Transaction', @LockTimeout = 15000; "
                    "SELECT @result"
                ),
                {"resource": "quantpulse:paper-account-execution"},
            )
            lock_result = result.scalar()
            if lock_result is not None and int(lock_result) < 0:
                raise RuntimeError("Could not acquire paper account execution lock")
        return True

    def ensure_table(self, db):
        if not USING_SQLITE_FALLBACK:
            return

        engine = db.get_bind()
        PaperTrade.__table__.create(bind=engine, checkfirst=True)
        existing = {
            column["name"]
            for column in inspect(engine).get_columns(PaperTrade.__tablename__)
        }
        evidence_columns = {
            "data_generation_id": "VARCHAR(100)",
            "validation_contract_version": "VARCHAR(100)",
            "fill_model_version": "VARCHAR(100)",
            "planned_entry_price": "FLOAT",
            "entry_slippage_percent": "FLOAT",
            "exit_slippage_percent": "FLOAT",
            "funding_rate_snapshot": "FLOAT",
            "funding_event_count": "INTEGER",
            "funding_cost_percent": "FLOAT",
            "open_interest_snapshot": "FLOAT",
            "open_interest_change_percent": "FLOAT",
            "exit_policy": "VARCHAR(50)",
            "initial_stop_loss": "FLOAT",
            "target1_fraction": "FLOAT",
            "remaining_position_fraction": "FLOAT",
            "max_hold_hours": "INTEGER",
            "target1_hit_at": "DATETIME",
            "target1_exit_price": "FLOAT",
            "exit_monitor_timeframe": "VARCHAR(10)",
            "last_exit_evaluated_at": "DATETIME",
            "paper_capital_at_entry_inr": "FLOAT",
            "allocation_percent": "FLOAT",
            "position_notional_inr": "FLOAT",
            "leverage": "FLOAT",
            "margin_used_inr": "FLOAT",
            "partial_realized_pnl_inr": "FLOAT",
            "realized_pnl_inr": "FLOAT",
        }
        for column, definition in evidence_columns.items():
            if column not in existing:
                db.execute(
                    text(
                        f"ALTER TABLE paper_trades ADD COLUMN {column} {definition}"
                    )
                )
        db.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_paper_trades_one_open_symbol ON paper_trades(symbol) "
                "WHERE status = 'OPEN'"
            )
        )
        db.commit()

    def get_open_trades(self, db):
        self.ensure_table(db)

        return db.query(PaperTrade).filter(PaperTrade.status == "OPEN").all()

    def ensure_staged_exit_policy(self, db, trade):
        """Apply the official staged policy to an existing open paper trade."""
        levels = build_policy_trade_levels(
            trade.side,
            trade.entry_price,
            symbol=trade.symbol,
            timeframe=trade.entry_timeframe,
            confidence=trade.confidence or 0,
            fee_bps=getattr(trade, "fee_bps", None) or 7.5,
            price_precision=_price_precision(trade.entry_price),
        )
        if levels is None:
            return False

        target1_complete = getattr(trade, "target1_hit_at", None) is not None
        desired_stop = (
            float(trade.entry_price)
            if target1_complete
            else levels["stop_loss"]
        )
        desired_remaining = 0.5 if target1_complete else 1.0
        values = {
            "exit_policy": PAPER_STAGED_EXIT_POLICY,
            "initial_stop_loss": levels["stop_loss"],
            "stop_loss": desired_stop,
            "target1": levels["target1"],
            "target2": levels["target2"],
            "target1_fraction": levels["target1_fraction"],
            "remaining_position_fraction": desired_remaining,
            "max_hold_hours": levels["max_hold_hours"],
            "exit_monitor_timeframe": PAPER_EXIT_MONITOR_TIMEFRAME,
            "last_exit_evaluated_at": (
                getattr(trade, "last_exit_evaluated_at", None)
                or getattr(trade, "opened_at", None)
            ),
        }
        trade_changed = any(
            not _same_policy_value(getattr(trade, key, None), value)
            for key, value in values.items()
        )
        linked_plan = (
            db.query(TradePlan)
            .filter(TradePlan.id == getattr(trade, "trade_plan_id", None))
            .first()
        )
        plan_values = {
            "stop_loss": levels["stop_loss"],
            "target1": levels["target1"],
            "target2": levels["target2"],
            "risk_reward": levels["target2_net_risk_reward"],
            "exit_policy": PAPER_STAGED_EXIT_POLICY,
            "target1_fraction": levels["target1_fraction"],
            "max_hold_hours": levels["max_hold_hours"],
        }
        plan_changed = linked_plan is not None and any(
            not _same_policy_value(getattr(linked_plan, key, None), value)
            for key, value in plan_values.items()
        )
        if not trade_changed and not plan_changed:
            return False

        for key, value in values.items():
            setattr(trade, key, value)

        if linked_plan is not None:
            for key, value in plan_values.items():
                setattr(linked_plan, key, value)

        commit_or_rollback(db)
        db.refresh(trade)
        return True

    def list_trades(self, db, status=None, symbol=None, limit=50):
        self.ensure_table(db)
        query = db.query(PaperTrade)

        if status:
            query = query.filter(PaperTrade.status == status)

        if symbol:
            query = query.filter(PaperTrade.symbol == symbol)

        query = query.order_by(PaperTrade.created_at.desc())
        if limit is not None:
            query = query.limit(limit)

        return query.all()

    def all_trades(self, db, symbol=None):
        self.ensure_table(db)
        query = db.query(PaperTrade)

        if symbol:
            query = query.filter(PaperTrade.symbol == symbol)

        return query.all()

    def has_open_trade(self, db, symbol, side=None):
        """Return whether the symbol already has an active position.

        ``side`` remains accepted for older callers but is intentionally not
        part of the lock key. QP-TI-001 permits one open trade per symbol
        across every timeframe and direction.
        """
        self.ensure_table(db)

        return (
            db.query(PaperTrade)
            .filter(PaperTrade.symbol == str(symbol).upper())
            .filter(PaperTrade.status == "OPEN")
            .first()
            is not None
        )

    def has_trade_for_plan(self, db, trade_plan_id):
        self.ensure_table(db)

        return (
            db.query(PaperTrade)
            .filter(PaperTrade.trade_plan_id == trade_plan_id)
            .first()
            is not None
        )

    def save_candidate(self, db, candidate):
        self.ensure_table(db)
        trade_plan = candidate["trade_plan"]
        authorization_risk = candidate["risk_decision"]
        risk = candidate.get("execution_risk") or authorization_risk
        fill_profile = candidate.get("fill_profile") or {}
        market_context = candidate.get("market_context") or {}
        entry_price = fill_profile.get("entry_fill_price", trade_plan["entry_price"])
        policy_levels = build_policy_trade_levels(
            candidate["side"],
            entry_price,
            symbol=candidate["symbol"],
            timeframe=trade_plan.get("entry_timeframe"),
            confidence=(
                risk.get("confidence") or trade_plan.get("confidence") or 0
            ),
            fee_bps=fill_profile.get("fee_bps", 7.5),
            price_precision=_price_precision(entry_price),
        )
        risk_reward = (
            policy_levels["target2_net_risk_reward"]
            if policy_levels is not None
            else fill_profile.get("effective_risk_reward", risk["risk_reward"])
        )
        stop_loss = (
            policy_levels["stop_loss"]
            if policy_levels is not None
            else trade_plan["stop_loss"]
        )
        target1 = (
            policy_levels["target1"]
            if policy_levels is not None
            else trade_plan["target1"]
        )
        target2 = (
            policy_levels["target2"]
            if policy_levels is not None
            else trade_plan["target2"]
        )
        opened_at = datetime.utcnow()
        paper_sizing = candidate.get("paper_sizing") or build_inr_paper_sizing(
            risk.get("confidence") or trade_plan.get("confidence") or 0,
            fee_bps=fill_profile.get("fee_bps", 7.5),
        )
        paper_trade = PaperTrade(
            trade_plan_id=trade_plan["id"],
            risk_decision_id=authorization_risk["id"],
            thesis_id=trade_plan.get("thesis_id"),
            symbol=str(candidate["symbol"]).upper(),
            side=candidate["side"],
            entry_price=entry_price,
            stop_loss=stop_loss,
            target1=target1,
            target2=target2,
            position_size=risk["position_size"],
            risk_reward=risk_reward,
            risk_percent=risk["risk_percent"],
            confidence=risk["confidence"],
            mode=trade_plan.get("mode"),
            entry_timeframe=trade_plan.get("entry_timeframe"),
            timeframe_stack=trade_plan.get("timeframe_stack"),
            regime=trade_plan.get("regime"),
            data_generation_id=trade_plan.get("data_generation_id"),
            exit_policy=(
                policy_levels["name"]
                if policy_levels is not None
                else trade_plan.get("exit_policy")
            ),
            initial_stop_loss=stop_loss,
            target1_fraction=(
                policy_levels["target1_fraction"]
                if policy_levels is not None
                else trade_plan.get("target1_fraction")
            ),
            remaining_position_fraction=1.0,
            exit_monitor_timeframe=PAPER_EXIT_MONITOR_TIMEFRAME,
            last_exit_evaluated_at=opened_at,
            paper_capital_at_entry_inr=paper_sizing["paper_capital_inr"],
            allocation_percent=paper_sizing["allocation_percent"],
            position_notional_inr=paper_sizing["position_notional_inr"],
            leverage=paper_sizing["leverage"],
            margin_used_inr=paper_sizing["margin_used_inr"],
            partial_realized_pnl_inr=0.0,
            max_hold_hours=(
                policy_levels["max_hold_hours"]
                if policy_levels is not None
                else trade_plan.get("max_hold_hours")
            ),
            validation_contract_version=candidate.get("validation_contract_version"),
            fill_model_version=fill_profile.get("model"),
            planned_entry_price=fill_profile.get(
                "planned_entry_price",
                trade_plan.get("entry_price"),
            ),
            entry_slippage_percent=fill_profile.get("entry_slippage_pct"),
            funding_rate_snapshot=market_context.get("fundingRate"),
            open_interest_snapshot=market_context.get("openInterest"),
            open_interest_change_percent=market_context.get(
                "openInterestChangePercent"
            ),
            fee_bps=float(fill_profile.get("fee_bps", 7.5)),
            status="OPEN",
            opened_at=opened_at,
        )

        db.add(paper_trade)
        flush_or_rollback(db)
        PaperWalletLedgerRepository().append_event(
            db,
            event_key=f"paper_trade:{paper_trade.id}:ENTRY",
            paper_trade_id=paper_trade.id,
            symbol=paper_trade.symbol,
            event_type="ENTRY",
            position_notional_inr=paper_trade.position_notional_inr,
            margin_inr=paper_trade.margin_used_inr,
            position_fraction=1.0,
            created_at=opened_at,
        )

        if paper_trade.thesis_id:
            TradeThesisRepository().attach_paper_trade(
                db,
                paper_trade.thesis_id,
                paper_trade.id,
                commit=False,
            )

        commit_or_rollback(db)
        db.refresh(paper_trade)

        return paper_trade

    def apply_target1(
        self,
        db,
        trade,
        exit_price,
        candle_time=None,
        evaluated_at=None,
    ):
        """Record a partial paper exit and protect the remainder at entry."""
        fraction = float(getattr(trade, "target1_fraction", None) or 0.5)
        trade.target1_fraction = fraction
        trade.remaining_position_fraction = max(0.0, 1.0 - fraction)
        trade.target1_hit_at = candle_time or datetime.utcnow()
        trade.target1_exit_price = float(exit_price)
        trade.stop_loss = float(trade.entry_price)
        _ensure_trade_sizing_snapshot(trade)
        gross_leg_percent = _directional_pnl_percent(
            trade.side,
            trade.entry_price,
            exit_price,
        )
        fee_percent = (float(getattr(trade, "fee_bps", 7.5) or 0) * 2) / 100
        contribution_percent = (gross_leg_percent - fee_percent) * fraction
        partial_pnl_inr = round(
            float(trade.position_notional_inr) * contribution_percent / 100,
            2,
        )
        trade.partial_realized_pnl_inr = partial_pnl_inr
        if evaluated_at is not None:
            trade.last_exit_evaluated_at = evaluated_at
        PaperWalletLedgerRepository().append_event(
            db,
            event_key=f"paper_trade:{trade.id}:TARGET1",
            paper_trade_id=trade.id,
            symbol=trade.symbol,
            event_type="TARGET1_REALIZED",
            delta_inr=partial_pnl_inr,
            position_notional_inr=trade.position_notional_inr,
            margin_inr=float(trade.margin_used_inr) * fraction,
            position_fraction=fraction,
            pnl_percent=contribution_percent,
            created_at=trade.target1_hit_at,
        )
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
        trade.exit_price = exit_price
        trade.result = result
        if fill_profile:
            trade.exit_slippage_percent = fill_profile.get("exit_slippage_pct")

        gross_pnl = self._gross_pnl_percent(trade, exit_price)

        fee_bps = float(getattr(trade, "fee_bps", 7.5) or 0)
        fees_percent = (fee_bps * 2) / 100
        funding_rates = self._funding_rates_during_trade(db, trade, closed_at)
        funding_direction = 1 if trade.side == "LONG" else -1
        target1_hit_at = getattr(trade, "target1_hit_at", None)
        remaining_fraction = float(
            getattr(trade, "remaining_position_fraction", None) or 1.0
        )
        funding_cost_percent = sum(
            rate
            * 100
            * funding_direction
            * (remaining_fraction if target1_hit_at and event_time > target1_hit_at else 1.0)
            for event_time, rate in funding_rates
        )
        trade.gross_pnl_percent = round(gross_pnl, 4)
        trade.fees_percent = round(fees_percent, 4)
        trade.funding_event_count = len(funding_rates)
        trade.funding_cost_percent = round(funding_cost_percent, 6)
        trade.pnl_percent = round(
            gross_pnl - fees_percent - funding_cost_percent,
            4,
        )
        _ensure_trade_sizing_snapshot(trade)
        trade.realized_pnl_inr = round(
            float(trade.position_notional_inr) * trade.pnl_percent / 100,
            2,
        )
        already_realized = float(
            getattr(trade, "partial_realized_pnl_inr", None) or 0
        )
        final_delta_inr = round(trade.realized_pnl_inr - already_realized, 2)
        PaperWalletLedgerRepository().append_event(
            db,
            event_key=f"paper_trade:{trade.id}:CLOSE",
            paper_trade_id=trade.id,
            symbol=trade.symbol,
            event_type="FINAL_CLOSE_REALIZED",
            delta_inr=final_delta_inr,
            position_notional_inr=trade.position_notional_inr,
            margin_inr=float(trade.margin_used_inr) * remaining_fraction,
            position_fraction=remaining_fraction,
            pnl_percent=(
                final_delta_inr / float(trade.position_notional_inr) * 100
            ),
            created_at=closed_at,
        )
        if result == "TIME_EXIT":
            trade.result = "WIN" if trade.pnl_percent > 0 else "LOSS"
        trade.closed_at = closed_at

        if getattr(trade, "thesis_id", None):
            TradeThesisRepository().set_lifecycle_state(
                db,
                trade.thesis_id,
                "COMPLETED" if trade.result == "WIN" else "INVALIDATED",
                reason=f"Paper trade closed with result {trade.result}",
                commit=False,
            )

        # No plan generated while this position was active may remain queued
        # after the symbol lock is released. The next pipeline stages must
        # reconstruct a fresh four-timeframe opportunity.
        open_plans = (
            db.query(TradePlan)
            .filter(TradePlan.symbol == trade.symbol)
            .filter(TradePlan.status == "OPEN")
            .all()
        )
        for plan in open_plans:
            plan.status = "CLOSED"
            plan.closed_at = closed_at
            if plan.id == trade.trade_plan_id:
                plan.result = trade.result
                plan.exit_price = exit_price
            else:
                plan.result = "STALE_AFTER_CLOSE"
                plan.exit_price = plan.entry_price
                if getattr(plan, "thesis_id", None):
                    TradeThesisRepository().set_lifecycle_state(
                        db,
                        plan.thesis_id,
                        "INVALIDATED",
                        reason="Queued plan invalidated after active symbol trade closed",
                        commit=False,
                    )

        commit_or_rollback(db)
        db.refresh(trade)

        return trade

    @staticmethod
    def _gross_pnl_percent(trade, exit_price):
        def leg_pnl(price):
            if trade.side == "LONG":
                return ((price - trade.entry_price) / trade.entry_price) * 100
            return ((trade.entry_price - price) / trade.entry_price) * 100

        target1_exit = getattr(trade, "target1_exit_price", None)
        if target1_exit is None:
            return leg_pnl(exit_price)

        target1_fraction = float(
            getattr(trade, "target1_fraction", None) or 0.5
        )
        remaining_fraction = float(
            getattr(trade, "remaining_position_fraction", None)
            if getattr(trade, "remaining_position_fraction", None) is not None
            else 1.0 - target1_fraction
        )
        return (
            leg_pnl(float(target1_exit)) * target1_fraction
            + leg_pnl(exit_price) * remaining_fraction
        )

    @staticmethod
    def _funding_rates_during_trade(db, trade, closed_at):
        opened_at = getattr(trade, "opened_at", None)
        if opened_at is None:
            return []

        rows = (
            db.query(FundingRate)
            .filter(FundingRate.symbol == trade.symbol)
            .filter(FundingRate.funding_time > opened_at)
            .filter(FundingRate.funding_time <= closed_at)
            .order_by(FundingRate.funding_time.asc(), FundingRate.id.asc())
            .all()
        )
        # The collector can observe the same exchange funding event more than
        # once. Charge each exchange event once, keyed by its funding timestamp.
        rates_by_event = {}
        for row in rows:
            if row.funding_time is not None and row.rate is not None:
                rates_by_event[row.funding_time] = float(row.rate)
        return list(rates_by_event.items())


def _price_precision(price):
    price = float(price)
    if price < 1:
        return 6
    if price < 10:
        return 5
    if price < 100:
        return 4
    return 2


def _same_policy_value(current, desired):
    if isinstance(desired, float):
        try:
            return abs(float(current) - desired) <= 1e-9
        except (TypeError, ValueError):
            return False
    return current == desired


def _ensure_trade_sizing_snapshot(trade):
    if (
        getattr(trade, "position_notional_inr", None) is not None
        and getattr(trade, "margin_used_inr", None) is not None
    ):
        return
    sizing = build_inr_paper_sizing(
        getattr(trade, "confidence", None) or 0,
        leverage=getattr(trade, "leverage", None) or 5.0,
        fee_bps=getattr(trade, "fee_bps", None) or 7.5,
    )
    trade.paper_capital_at_entry_inr = sizing["paper_capital_inr"]
    trade.allocation_percent = sizing["allocation_percent"]
    trade.position_notional_inr = sizing["position_notional_inr"]
    trade.leverage = sizing["leverage"]
    trade.margin_used_inr = sizing["margin_used_inr"]


def _directional_pnl_percent(side, entry_price, exit_price):
    entry = float(entry_price)
    exit_value = float(exit_price)
    if str(side or "").upper() == "LONG":
        return (exit_value - entry) / entry * 100
    return (entry - exit_value) / entry * 100
