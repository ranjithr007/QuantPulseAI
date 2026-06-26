from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import and_, func
from sqlalchemy import insert
from sqlalchemy import inspect
from sqlalchemy import select

from app.database.sqlserver import SessionLocal

from app.database.models.risk_decision import RiskDecision
from app.features.point_in_time_feature_service import build_decision_snapshot
from app.features.point_in_time_feature_service import persist_decision_snapshot
from app.repositories.trade_thesis_repository import TradeThesisRepository


class RiskRepository:

    def save(self, data):

        db = SessionLocal()

        try:
            targets = data.get("targets") or {}
            columns = _risk_decision_columns(db)
            payload = dict(
                symbol=data["symbol"],
                signal=data.get("signal"),
                decision=data.get("decision"),
                entry_price=data.get("entry"),
                stop_loss=data.get("stop_loss"),
                target1=targets.get("t1"),
                target2=targets.get("t2"),
                position_size=data.get("position_size"),
                risk_reward=data.get("risk_reward"),
                confidence=data.get("confidence"),
                risk_percent=data.get("risk_percent", 1),
                created_at=datetime.utcnow(),
            )
            thesis_id = data.get("thesis_id")
            if thesis_id is not None and "thesis_id" in columns:
                payload["thesis_id"] = thesis_id

            result = db.execute(
                insert(RiskDecision.__table__).values(payload)
            )
            risk_id = None
            try:
                inserted_key = result.inserted_primary_key
                if inserted_key:
                    risk_id = inserted_key[0]
            except Exception:
                risk_id = None

            if thesis_id and risk_id:
                TradeThesisRepository().attach_risk_decision(
                    db,
                    thesis_id,
                    risk_id,
                    commit=False,
                )

            persist_decision_snapshot(
                db,
                build_decision_snapshot(
                    data["symbol"],
                    data.get("timeframe") or "5m",
                    decision=data.get("decision"),
                    source_timestamp=data.get("source_timestamp") or datetime.utcnow(),
                    effective_timestamp=data.get("effective_timestamp") or datetime.utcnow(),
                    confidence=data.get("confidence"),
                    regime=data.get("regime"),
                    thesis_id=thesis_id,
                    signal={
                        "signal": data.get("signal"),
                        "entry": data.get("entry"),
                        "stop_loss": data.get("stop_loss"),
                        "targets": targets,
                        "risk_reward": data.get("risk_reward"),
                        "position_size": data.get("position_size"),
                    },
                    trade_plan={
                        "entry": data.get("entry"),
                        "stop_loss": data.get("stop_loss"),
                        "target1": targets.get("t1"),
                        "target2": targets.get("t2"),
                    },
                    context={
                        "risk_percent": data.get("risk_percent", 1),
                        "reason": data.get("reason"),
                    },
                ),
            )

        finally:

            db.close()

    def latest(self, symbol):

        db = SessionLocal()

        try:

            return self.latest_for_symbol(db, symbol)

        finally:

            db.close()

    def latest_for_symbol(self, db, symbol):
        columns = _risk_decision_select_columns(db)
        table = RiskDecision.__table__
        row = (
            db.execute(
                select(*columns)
                .select_from(table)
                .where(table.c.symbol == symbol)
                .order_by(table.c.created_at.desc())
            )
            .first()
        )
        return _row_to_namespace(row)

    def latest_for_symbols(self, db, symbols):
        normalized_symbols = list(dict.fromkeys(symbols))
        if not normalized_symbols:
            return {}

        table = RiskDecision.__table__
        columns = _risk_decision_select_columns(db)
        latest_created = (
            select(
                table.c.symbol.label("symbol"),
                func.max(RiskDecision.created_at).label("created_at"),
            )
            .where(table.c.symbol.in_(normalized_symbols))
            .group_by(table.c.symbol)
            .subquery()
        )
        rows = (
            db.execute(
                select(*columns)
                .select_from(
                    table.join(
                        latest_created,
                        and_(
                            table.c.symbol == latest_created.c.symbol,
                            table.c.created_at == latest_created.c.created_at,
                        ),
                    )
                )
            )
            .all()
        )

        return {
            row._mapping["symbol"]: _row_to_namespace(row)
            for row in rows
        }


def _risk_decision_columns(db):
    return set(_table_column_names(db, RiskDecision.__tablename__))


def _risk_decision_select_columns(db):
    table = RiskDecision.__table__
    available = _risk_decision_columns(db)
    return [
        getattr(table.c, column.name)
        for column in table.columns
        if column.name in available
    ]


def _table_column_names(db, table_name):
    try:
        inspector = inspect(db.get_bind())
        return [column["name"] for column in inspector.get_columns(table_name)]
    except Exception:
        return [column.name for column in RiskDecision.__table__.columns]


def _row_to_namespace(row):
    if row is None:
        return None

    return SimpleNamespace(**dict(row._mapping))
