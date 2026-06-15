from sqlalchemy import Column
from sqlalchemy import *

from app.database.sqlserver import Base


class Liquidation(Base):

    __tablename__="liquidations"


    id=Column(
        BigInteger,
        primary_key=True
    )


    symbol=Column(String(20))


    side=Column(String(10))


    price=Column(Float)


    quantity=Column(Float)


    event_time=Column(DateTime)