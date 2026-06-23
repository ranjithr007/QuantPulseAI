from sqlalchemy import and_, func

from app.database.sqlserver import SessionLocal

from app.database.models.risk_decision import RiskDecision


class RiskRepository:

    def save(self, data):

        db = SessionLocal()

        try:
            targets = data.get("targets") or {}

            risk = RiskDecision(
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
            )

            db.add(risk)

            db.commit()

        finally:

            db.close()

    def latest(self, symbol):

        db = SessionLocal()

        try:

            return self.latest_for_symbol(db, symbol)

        finally:

            db.close()

    def latest_for_symbol(self, db, symbol):

        return (
            db.query(RiskDecision)
            .filter(RiskDecision.symbol == symbol)
            .order_by(RiskDecision.created_at.desc())
            .first()
        )

    def latest_for_symbols(self, db, symbols):
        normalized_symbols = list(dict.fromkeys(symbols))
        if not normalized_symbols:
            return {}

        latest_created = (
            db.query(
                RiskDecision.symbol.label("symbol"),
                func.max(RiskDecision.created_at).label("created_at"),
            )
            .filter(RiskDecision.symbol.in_(normalized_symbols))
            .group_by(RiskDecision.symbol)
            .subquery()
        )
        rows = (
            db.query(RiskDecision)
            .join(
                latest_created,
                and_(
                    RiskDecision.symbol == latest_created.c.symbol,
                    RiskDecision.created_at == latest_created.c.created_at,
                ),
            )
            .all()
        )

        return {row.symbol: row for row in rows}
