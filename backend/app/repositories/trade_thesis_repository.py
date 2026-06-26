import json
from datetime import datetime

from sqlalchemy import inspect
from sqlalchemy import text

from app.database.models.trade_thesis import TradeThesis
from app.repositories._db_utils import commit_or_rollback
from app.repositories._db_utils import flush_or_rollback
from app.repositories.thesis_snapshot_repository import save_thesis_snapshot


class TradeThesisRepository:
    def ensure_table(self, db):
        TradeThesis.__table__.create(bind=db.get_bind(), checkfirst=True)

    def create_for_trade_plan(self, db, trade, scenario=None, contradiction=None, commit=False):
        self.ensure_table(db)
        payload = _build_payload_from_trade(trade, scenario=scenario, contradiction=contradiction)
        thesis = TradeThesis(**payload)
        db.add(thesis)
        flush_or_rollback(db)
        save_thesis_snapshot(
            db,
            thesis,
            source_timestamp=getattr(thesis, "created_at", None),
            effective_timestamp=getattr(thesis, "created_at", None),
        )
        if commit:
            commit_or_rollback(db)
            db.refresh(thesis)
        return thesis

    def attach_risk_decision(self, db, thesis_id, risk_decision_id, commit=False):
        thesis = self.get_by_id(db, thesis_id)
        if thesis is None:
            return None

        thesis.risk_decision_id = risk_decision_id
        thesis.updated_at = datetime.utcnow()
        save_thesis_snapshot(
            db,
            thesis,
            source_timestamp=thesis.updated_at,
            effective_timestamp=thesis.updated_at,
        )
        if commit:
            commit_or_rollback(db)
            db.refresh(thesis)
        return thesis

    def attach_paper_trade(self, db, thesis_id, paper_trade_id, commit=False):
        thesis = self.get_by_id(db, thesis_id)
        if thesis is None:
            return None

        thesis.paper_trade_id = paper_trade_id
        thesis.updated_at = datetime.utcnow()
        save_thesis_snapshot(
            db,
            thesis,
            source_timestamp=thesis.updated_at,
            effective_timestamp=thesis.updated_at,
        )
        if commit:
            commit_or_rollback(db)
            db.refresh(thesis)
        return thesis

    def set_lifecycle_state(self, db, thesis_id, lifecycle_state, reason=None, commit=True):
        thesis = self.get_by_id(db, thesis_id)
        if thesis is None:
            return None

        thesis.lifecycle_state = lifecycle_state
        thesis.lifecycle_reason = reason
        thesis.updated_at = datetime.utcnow()
        if lifecycle_state == "INVALIDATED":
            thesis.invalidated_at = datetime.utcnow()
        if lifecycle_state in {"COMPLETED", "RESOLVED"}:
            thesis.resolved_at = datetime.utcnow()

        save_thesis_snapshot(
            db,
            thesis,
            source_timestamp=thesis.updated_at,
            effective_timestamp=thesis.updated_at,
        )

        if commit:
            commit_or_rollback(db)
            db.refresh(thesis)

        return thesis

    def get_by_id(self, db, thesis_id):
        self.ensure_table(db)
        return db.query(TradeThesis).filter(TradeThesis.id == thesis_id).first()

    def latest_for_symbol(self, db, symbol):
        self.ensure_table(db)
        return (
            db.query(TradeThesis)
            .filter(TradeThesis.symbol == symbol)
            .order_by(TradeThesis.created_at.desc(), TradeThesis.id.desc())
            .first()
        )

    def list_theses(self, db, symbol=None, lifecycle_state=None, limit=100):
        self.ensure_table(db)
        query = db.query(TradeThesis)
        if symbol:
            query = query.filter(TradeThesis.symbol == symbol)
        if lifecycle_state:
            query = query.filter(TradeThesis.lifecycle_state == lifecycle_state)

        rows = (
            query.order_by(TradeThesis.created_at.desc(), TradeThesis.id.desc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
        return [serialize_thesis(row) for row in rows]


def ensure_trade_thesis_lineage_schema(engine):
    TradeThesis.__table__.create(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    dialect_name = getattr(engine.dialect, "name", "")

    for table_name, index_name in _LINEAGE_TABLES:
        if table_name not in inspector.get_table_names():
            continue

        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "thesis_id" not in columns:
            _add_thesis_id_column(engine, dialect_name, table_name)
            inspector = inspect(engine)

        indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name not in indexes:
            _create_thesis_id_index(engine, dialect_name, table_name, index_name)
            inspector = inspect(engine)


def _add_thesis_id_column(engine, dialect_name, table_name):
    table_ref = _qualified_table_name(dialect_name, table_name)
    if dialect_name == "mssql":
        statement = f"ALTER TABLE {table_ref} ADD thesis_id INT NULL"
    else:
        statement = f"ALTER TABLE {table_ref} ADD COLUMN thesis_id INTEGER"

    with engine.begin() as connection:
        connection.execute(text(statement))


def _create_thesis_id_index(engine, dialect_name, table_name, index_name):
    table_ref = _qualified_table_name(dialect_name, table_name)
    statement = f"CREATE INDEX {index_name} ON {table_ref} (thesis_id)"

    with engine.begin() as connection:
        connection.execute(text(statement))


def _qualified_table_name(dialect_name, table_name):
    if dialect_name == "mssql":
        return f"dbo.{table_name}"

    return table_name


_LINEAGE_TABLES = (
    ("trade_plans", "ix_trade_plans_thesis_id"),
    ("risk_decisions", "ix_risk_decisions_thesis_id"),
    ("paper_trades", "ix_paper_trades_thesis_id"),
)


def serialize_thesis(thesis):
    return {
        "id": thesis.id,
        "thesis_key": thesis.thesis_key,
        "symbol": thesis.symbol,
        "side": thesis.side,
        "title": thesis.title,
        "lifecycle_state": thesis.lifecycle_state,
        "lifecycle_reason": thesis.lifecycle_reason,
        "source_signal": thesis.source_signal,
        "confidence": thesis.confidence,
        "mode": thesis.mode,
        "entry_timeframe": thesis.entry_timeframe,
        "timeframe_stack": thesis.timeframe_stack,
        "regime": thesis.regime,
        "trade_plan_id": thesis.trade_plan_id,
        "risk_decision_id": thesis.risk_decision_id,
        "paper_trade_id": thesis.paper_trade_id,
        "assumptions": _json_value(thesis.assumptions_json, {}),
        "invalidation": _json_value(thesis.invalidation_json, {}),
        "targets": _json_value(thesis.targets_json, {}),
        "scenario": _json_value(thesis.scenario_json, None),
        "contradiction": _json_value(thesis.contradiction_json, None),
        "created_at": thesis.created_at,
        "updated_at": thesis.updated_at,
        "invalidated_at": thesis.invalidated_at,
        "resolved_at": thesis.resolved_at,
    }


def _build_payload_from_trade(trade, scenario=None, contradiction=None):
    target2 = getattr(trade, "target2", None)
    target3 = getattr(trade, "target3", None)
    thesis_key = f"{trade.symbol}:{trade.side}:{getattr(trade, 'id', 'draft')}"
    assumptions = {
        "thesis_version": "trade_thesis_v1",
        "symbol": trade.symbol,
        "side": trade.side,
        "entry_price": getattr(trade, "entry_price", None),
        "confidence": getattr(trade, "confidence", None),
        "mode": getattr(trade, "mode", None),
        "entry_timeframe": getattr(trade, "entry_timeframe", None),
        "timeframe_stack": getattr(trade, "timeframe_stack", None),
        "regime": getattr(trade, "regime", None),
    }
    invalidation = getattr(trade, "invalidation", None) or {
        "price": getattr(trade, "stop_loss", None),
        "rule": f"Close beyond stop loss for {trade.side}",
        "lifecycle_state": "INVALIDATED",
    }
    targets = {
        "target1": getattr(trade, "target1", None),
        "target2": target2,
        "target3": target3,
        "risk_reward": getattr(trade, "risk_reward", None),
    }

    return {
        "thesis_key": thesis_key,
        "symbol": trade.symbol,
        "side": trade.side,
        "title": f"{trade.symbol} {trade.side} thesis",
        "lifecycle_state": "ACTIVE" if getattr(trade, "entry_price", None) is not None else "DRAFT",
        "lifecycle_reason": None,
        "source_signal": getattr(trade, "side", None),
        "confidence": getattr(trade, "confidence", None),
        "mode": getattr(trade, "mode", None),
        "entry_timeframe": getattr(trade, "entry_timeframe", None),
        "timeframe_stack": getattr(trade, "timeframe_stack", None),
        "regime": getattr(trade, "regime", None),
        "trade_plan_id": getattr(trade, "id", None),
        "risk_decision_id": None,
        "paper_trade_id": None,
        "assumptions_json": json.dumps(assumptions, sort_keys=True, default=str),
        "invalidation_json": json.dumps(invalidation, sort_keys=True, default=str),
        "targets_json": json.dumps(targets, sort_keys=True, default=str),
        "scenario_json": json.dumps(scenario, sort_keys=True, default=str) if scenario is not None else None,
        "contradiction_json": json.dumps(contradiction, sort_keys=True, default=str) if contradiction is not None else None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


def _json_value(value, fallback):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback
