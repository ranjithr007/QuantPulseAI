from datetime import datetime

from sqlalchemy import inspect, text

from app.database.models.funding_rates import FundingRate
from app.database.models.paper_trade import PaperTrade
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.repositories._db_utils import commit_or_rollback
from app.repositories._db_utils import flush_or_rollback
from app.repositories.trade_thesis_repository import TradeThesisRepository


class PaperTradeRepository:
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
        }
        for column, definition in evidence_columns.items():
            if column not in existing:
                db.execute(
                    text(
                        f"ALTER TABLE paper_trades ADD COLUMN {column} {definition}"
                    )
                )
        db.commit()

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
        risk = candidate["risk_decision"]
        fill_profile = candidate.get("fill_profile") or {}
        market_context = candidate.get("market_context") or {}
        entry_price = fill_profile.get("entry_fill_price", trade_plan["entry_price"])
        risk_reward = fill_profile.get("effective_risk_reward", risk["risk_reward"])
        paper_trade = PaperTrade(
            trade_plan_id=trade_plan["id"],
            risk_decision_id=risk["id"],
            thesis_id=trade_plan.get("thesis_id"),
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
            mode=trade_plan.get("mode"),
            entry_timeframe=trade_plan.get("entry_timeframe"),
            timeframe_stack=trade_plan.get("timeframe_stack"),
            regime=trade_plan.get("regime"),
            data_generation_id=trade_plan.get("data_generation_id"),
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
            fee_bps=float(fill_profile.get("fee_bps", 4.0)),
            status="OPEN",
        )

        db.add(paper_trade)
        flush_or_rollback(db)

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

    def close_trade(self, db, trade, exit_price, result, fill_profile=None):
        closed_at = datetime.utcnow()
        trade.status = "CLOSED"
        trade.exit_price = exit_price
        trade.result = result
        if fill_profile:
            trade.exit_slippage_percent = fill_profile.get("exit_slippage_pct")

        if trade.side == "LONG":
            gross_pnl = ((exit_price - trade.entry_price) / trade.entry_price) * 100
        else:
            gross_pnl = ((trade.entry_price - exit_price) / trade.entry_price) * 100

        fee_bps = float(getattr(trade, "fee_bps", 4.0) or 0)
        fees_percent = (fee_bps * 2) / 100
        funding_rates = self._funding_rates_during_trade(db, trade, closed_at)
        funding_direction = 1 if trade.side == "LONG" else -1
        funding_cost_percent = (
            sum(funding_rates) * 100 * funding_direction
        )
        trade.gross_pnl_percent = round(gross_pnl, 4)
        trade.fees_percent = round(fees_percent, 4)
        trade.funding_event_count = len(funding_rates)
        trade.funding_cost_percent = round(funding_cost_percent, 6)
        trade.pnl_percent = round(
            gross_pnl - fees_percent - funding_cost_percent,
            4,
        )
        trade.closed_at = closed_at

        if getattr(trade, "thesis_id", None):
            TradeThesisRepository().set_lifecycle_state(
                db,
                trade.thesis_id,
                "COMPLETED" if result == "WIN" else "INVALIDATED",
                reason=f"Paper trade closed with result {result}",
                commit=False,
            )

        commit_or_rollback(db)
        db.refresh(trade)

        return trade

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
        return list(rates_by_event.values())
