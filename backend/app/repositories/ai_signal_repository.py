from app.database.models.ai_signals import AISignal


class AISignalRepository:

    def save(self, db, data):

        db.add(AISignal(**data))

        db.commit()

    def latest(self, db, symbol):

        return (
            db.query(AISignal)
            .filter(AISignal.symbol == symbol)
            .order_by(AISignal.created_at.desc())
            .first()
        )
