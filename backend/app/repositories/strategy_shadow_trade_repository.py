from datetime import datetime
from hashlib import blake2b

from sqlalchemy import and_, case, func, inspect, or_, text

from app.database.models.funding_rates import FundingRate
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.paper_trading.exit_policy import PAPER_EXIT_MONITOR_TIMEFRAME
from app.paper_trading.exit_policy import PAPER_TARGET1_FRACTION
from app.paper_trading.exit_policy import build_policy_trade_levels
from app.paper_trading.exit_policy import approved_adaptive_entry_levels
from app.paper_trading.exit_policy import target1_protection_stop
from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.repositories._db_utils import commit_or_rollback, flush_or_rollback
from app.paper_trading.exit_lock import advance_exit_checkpoint
from app.paper_trading.exit_evidence import entry_evidence_fields, record_exit_evidence
from app.paper_trading.evidence_scope import QA_PAPER_SYMBOL_PREFIX
from app.strategies.registry import strategy_definition


def _is_frozen_experiment_revision(strategy_id, strategy_version):
    """Only numbered frozen revisions share admission, never auto candidates."""
    definition = strategy_definition(strategy_id) or {}
    prefix = f"{str(strategy_id or '').lower()}_v"
    version = str(strategy_version or "")
    revision = version[len(prefix):] if version.startswith(prefix) else ""
    return bool(
        definition.get("immutable_experiment") is True
        and definition.get("strategy_type") in {"ENTRY_CANDIDATE", "EXIT_CANDIDATE"}
        and definition.get("execution_scope") == "PAPER_ONLY"
        and definition.get("official_execution_enabled") is False
        and revision.isascii() and revision.isdecimal()
    )


class StrategyShadowTradeRepository:
    """Isolated Strategy Paper ledger with its own normalized virtual capital."""

    def acquire_book_execution_lock(self, db, strategy_id, strategy_version):
        """Serialize admission; frozen revisions share safety, not P&L cohorts."""
        shared_experiment = _is_frozen_experiment_revision(strategy_id, strategy_version)
        lock_version = "frozen-experiment" if shared_experiment else strategy_version
        resource = f"quantpulse:strategy-book:{strategy_id}:{lock_version}"
        dialect = str(db.get_bind().dialect.name).lower()
        if dialect == "sqlite":
            self.ensure_table(db)  # Schema initialization precedes reservation.
            if shared_experiment:
                # SQLite has no advisory lock. A zero-row write reserves its
                # writer transaction without changing trades or nesting BEGIN.
                # The executor retains this transaction through the final fill.
                db.execute(text("UPDATE strategy_shadow_trades SET id = id WHERE 1 = 0"))
        if dialect == "postgresql":
            key = int.from_bytes(blake2b(resource.encode(), digest_size=8).digest(), "big", signed=True)
            db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": key})
        elif dialect == "mssql":
            result = db.execute(text(
                "DECLARE @result int; EXEC @result = sp_getapplock "
                "@Resource = :resource, @LockMode = 'Exclusive', "
                "@LockOwner = 'Transaction', @LockTimeout = 15000; SELECT @result"
            ), {"resource": resource}).scalar()
            if result is not None and int(result) < 0:
                raise RuntimeError("Could not acquire strategy paper book execution lock")
        return True

    def ensure_table(self, db):
        if not USING_SQLITE_FALLBACK:
            return
        connection = db.connection()
        created = not inspect(connection).has_table(StrategyShadowTrade.__tablename__)
        if created:
            StrategyShadowTrade.__table__.create(bind=connection, checkfirst=True)
        # ``create(checkfirst=True)`` is intentionally idempotent. Inspecting
        # here also forces a clear failure when a legacy fallback schema is
        # missing the governed table rather than silently mixing ledgers.
        if StrategyShadowTrade.__tablename__ not in inspect(connection).get_table_names():
            raise RuntimeError("Strategy shadow ledger could not be initialized")
        existing = {column["name"] for column in inspect(connection).get_columns(StrategyShadowTrade.__tablename__)}
        changed = created
        for name, kind in {"trailing_activation_r": "FLOAT", "execution_evidence_json": "TEXT", "exit_evidence_json": "TEXT"}.items():
            if name not in existing:
                db.execute(text(f"ALTER TABLE strategy_shadow_trades ADD COLUMN {name} {kind}"))
                changed = True
        if changed:
            db.commit()

    def get_open_trades(self, db):
        self.ensure_table(db)
        return (
            db.query(StrategyShadowTrade)
            .filter(StrategyShadowTrade.status == "OPEN")
            .all()
        )

    def valuation_snapshot(self, db, *, strategy_id=None, strategy_version=None):
        """Consistent book cash/OPEN position snapshot without exit row locks."""
        self.ensure_table(db)
        scope = [or_(StrategyShadowTrade.symbol.is_(None),
                     ~func.upper(StrategyShadowTrade.symbol).like(f"{QA_PAPER_SYMBOL_PREFIX}%"))]
        if strategy_id is not None:
            scope.append(StrategyShadowTrade.strategy_id == strategy_id)
        if strategy_version is not None:
            scope.append(StrategyShadowTrade.strategy_version == strategy_version)
        realized = case(
            (StrategyShadowTrade.status == "CLOSED", func.coalesce(StrategyShadowTrade.realized_pnl_inr, 0.0)),
            (StrategyShadowTrade.status == "OPEN", func.coalesce(StrategyShadowTrade.partial_realized_pnl_inr, 0.0)),
            else_=0.0,
        )
        totals = db.query(func.coalesce(func.sum(realized), 0.0).label("realized_pnl_inr")).filter(*scope).subquery()
        rows = (
            db.query(StrategyShadowTrade, totals.c.realized_pnl_inr).select_from(totals)
            .outerjoin(StrategyShadowTrade, and_(*scope, StrategyShadowTrade.status == "OPEN"))
            .order_by(StrategyShadowTrade.id.asc()).populate_existing().all()
        )
        return {
            "open_trades": [row[0] for row in rows if row[0] is not None],
            "realized_pnl_inr": float(rows[0][1]),
            "valuation_snapshot_version": "SINGLE_STATEMENT_V1",
        }

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

    def risk_snapshot_trades(self, db, *, window_start, strategy_id=None, strategy_version=None):
        """Load only open positions and closed trades in the daily-risk window."""

        self.ensure_table(db)
        query = (
            db.query(StrategyShadowTrade)
            .filter(
                or_(
                    StrategyShadowTrade.status == "OPEN",
                    and_(
                        StrategyShadowTrade.status == "CLOSED",
                        StrategyShadowTrade.closed_at >= window_start,
                    ),
                )
            )
        )
        if strategy_id is not None:
            query = query.filter(StrategyShadowTrade.strategy_id == strategy_id)
        if strategy_version is not None:
            query = query.filter(StrategyShadowTrade.strategy_version == strategy_version)
        return query.all()

    def realized_pnl_by_strategy(self, db, strategy_keys):
        """Return exact lifetime realized P&L without hydrating trade history."""

        self.ensure_table(db)
        normalized_keys = {
            (str(strategy_id), str(strategy_version))
            for strategy_id, strategy_version in (strategy_keys or [])
            if strategy_id and strategy_version
        }
        if not normalized_keys:
            return {}

        scopes = [
            and_(
                StrategyShadowTrade.strategy_id == strategy_id,
                StrategyShadowTrade.strategy_version == strategy_version,
            )
            for strategy_id, strategy_version in normalized_keys
        ]
        realized = case(
            (
                StrategyShadowTrade.status == "CLOSED",
                func.coalesce(StrategyShadowTrade.realized_pnl_inr, 0.0),
            ),
            (
                StrategyShadowTrade.status == "OPEN",
                func.coalesce(StrategyShadowTrade.partial_realized_pnl_inr, 0.0),
            ),
            else_=0.0,
        )
        rows = (
            db.query(
                StrategyShadowTrade.strategy_id,
                StrategyShadowTrade.strategy_version,
                func.sum(realized).label("realized_pnl_inr"),
            )
            .filter(or_(*scopes))
            .group_by(
                StrategyShadowTrade.strategy_id,
                StrategyShadowTrade.strategy_version,
            )
            .all()
        )
        return {
            (row.strategy_id, row.strategy_version): round(
                float(row.realized_pnl_inr or 0.0),
                2,
            )
            for row in rows
        }

    def has_open_trade(self, db, strategy_id, strategy_version, symbol):
        self.ensure_table(db)
        query = (
            db.query(StrategyShadowTrade.strategy_version)
            .filter(StrategyShadowTrade.strategy_id == strategy_id)
            .filter(StrategyShadowTrade.symbol == str(symbol).upper())
            .filter(StrategyShadowTrade.status == "OPEN")
        )
        if _is_frozen_experiment_revision(strategy_id, strategy_version):
            # Numbered revisions share one active position per coin. Keep
            # historical auto/custom candidate books independently versioned.
            return any(
                _is_frozen_experiment_revision(strategy_id, row.strategy_version)
                for row in query.all()
            )
        return query.filter(StrategyShadowTrade.strategy_version == strategy_version).first() is not None

    def stop_reentry_history(
        self, db, *, strategy_id, strategy_version, symbol, side,
        window_start, versioned_history,
    ):
        """Extend only frozen admission cooldowns across numbered revisions.

        The executor keeps using its original versioned history for valuation,
        daily loss, capacity, learning and performance evidence.
        """
        if not _is_frozen_experiment_revision(strategy_id, strategy_version):
            return versioned_history
        self.ensure_table(db)
        rows = (
            db.query(StrategyShadowTrade)
            .filter(StrategyShadowTrade.strategy_id == strategy_id)
            .filter(StrategyShadowTrade.symbol == str(symbol).upper())
            .filter(StrategyShadowTrade.side == str(side).upper())
            .filter(StrategyShadowTrade.status == "CLOSED")
            .filter(StrategyShadowTrade.exit_reason == "STOP")
            .filter(StrategyShadowTrade.closed_at >= window_start)
            .all()
        )
        return [
            row for row in rows
            if _is_frozen_experiment_revision(strategy_id, row.strategy_version)
        ]

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
        levels = approved_adaptive_entry_levels(candidate, entry) or build_policy_trade_levels(
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
            **entry_evidence_fields(candidate),
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
        protected_stop = target1_protection_stop(
            trade.side,
            trade.entry_price,
            trade.target1,
            _price_precision(trade.entry_price),
        )
        trade.stop_loss = max(float(trade.stop_loss), protected_stop) if trade.side == "LONG" else min(float(trade.stop_loss), protected_stop)
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
        trade = advance_exit_checkpoint(db, trade, evaluated_at)
        commit_or_rollback(db)
        db.refresh(trade)
        return trade

    def close_trade(self, db, trade, exit_price, result, fill_profile=None):
        from app.paper_trading.exit_time import exit_evidence_time
        closed_at = exit_evidence_time(trade, fill_profile)
        trade.status = "CLOSED"
        trade.exit_price = float(exit_price)
        trade.exit_reason = str(
            (fill_profile or {}).get("trigger_type") or result or "EXIT"
        ).upper()
        trade.exit_slippage_percent = (fill_profile or {}).get(
            "exit_slippage_pct"
        )
        record_exit_evidence(trade, fill_profile, exit_price)
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
        # The trigger describes *how* the trade closed; WIN/LOSS describes the
        # final cost-adjusted outcome.  A protected trailing stop after T1 can
        # be profitable, so copying the monitor's STOP result corrupts strategy
        # statistics and any learning process built on top of them.
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
