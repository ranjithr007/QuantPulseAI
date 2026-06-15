from app.database.models.ai_signals import AISignal


class AISignalRepository:

    def save(self, db, data):

        db.add(AISignal(**data))

        db.commit()