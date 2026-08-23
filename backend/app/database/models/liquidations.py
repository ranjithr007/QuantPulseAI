from sqlalchemy import BigInteger
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String

from app.database.sqlserver import Base


class Liquidation(Base):

    __tablename__ = "liquidations"


    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )


    venue = Column(String(20), nullable=False, default="BINANCE")

    exchange_event_id = Column(String(40), nullable=True)

    symbol = Column(String(20))


    side = Column(String(10))


    price = Column(Float)


    quantity = Column(Float)

    value_usd = Column(Float)


    event_time = Column(DateTime)


Index(
    "uq_liquidations_exchange_event",
    Liquidation.venue,
    Liquidation.symbol,
    Liquidation.exchange_event_id,
    unique=True,
)
