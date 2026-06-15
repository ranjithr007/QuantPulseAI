from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Integer,
    DateTime
)

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class AIScore(Base):

    __tablename__ = "ai_scores"


    id = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )


    symbol = Column(
        String(20),
        index=True,
        nullable=False
    )


    trend_score = Column(Integer)

    liquidity_score = Column(Integer)

    derivative_score = Column(Integer)

    volatility_score = Column(Integer)

    whale_score = Column(Integer)

    sentiment_score = Column(Integer)


    final_score = Column(Integer)


    bias = Column(
        String(20)
    )


    confidence = Column(
        Integer
    )


    created_at = Column(
        DateTime,
        server_default=func.now()
    )