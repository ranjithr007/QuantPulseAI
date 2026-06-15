from app.database.sqlserver import SessionLocal

from app.database.models.risk_decision import RiskDecision


class RiskRepository:

    def save(self, data):

        db = SessionLocal()

        try:

            risk = RiskDecision(
                symbol=data["symbol"],
                signal=data["signal"],
                decision=data["decision"],
                entry_price=data["entry"],
                stop_loss=data["stop_loss"],
                target1=data["targets"]["t1"],
                target2=data["targets"]["t2"],
                position_size=data["position_size"],
                risk_reward=data["risk_reward"],
                confidence=data["confidence"],
                risk_percent=1,
            )

            db.add(risk)

            db.commit()

        finally:

            db.close()