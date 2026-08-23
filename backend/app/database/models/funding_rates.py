from sqlalchemy import Column
from sqlalchemy import BigInteger
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import DateTime
from sqlalchemy import Index
from sqlalchemy import Integer

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class FundingRate(Base):

    __tablename__ = "funding_rates"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    symbol = Column(String(20), index=True)

    rate = Column(Float)

    funding_time = Column(DateTime)

    created_at = Column(DateTime, server_default=func.now())


Index(
    "uq_funding_rates_symbol_event",
    FundingRate.symbol,
    FundingRate.funding_time,
    unique=True,
)
