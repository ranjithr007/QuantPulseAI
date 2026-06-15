from app.database.sqlserver import SessionLocal
from app.repositories.fusion_repository import FusionSignalRepository

from app.risk.risk_engine import RiskEngine

from app.repositories.risk_repository import RiskRepository


def run_risk_job():
    db = SessionLocal()
    fusion_repo = FusionSignalRepository()

    risk_repo = RiskRepository()

    engine = RiskEngine()

    signals = fusion_repo.get_latest_signals(db)

    for s in signals:

        result = engine.analyze(
            symbol=s.symbol,
            signal=s.decision,
            price=s.current_price,
            atr=s.atr,
            confidence=s.confidence,
        )

        risk_repo.save(result)
    
    db.close()
    print("Risk Engine Completed")