
from sqlalchemy import Column, BigInteger, String, Float, DateTime

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class AISignal(Base):

    __tablename__ = "ai_signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True)

    direction = Column(String(20))

    entry_price = Column(Float)

    target_price = Column(Float)

    confidence = Column(Float)

    reason = Column(String(500))

    created_at = Column(DateTime, server_default=func.now())