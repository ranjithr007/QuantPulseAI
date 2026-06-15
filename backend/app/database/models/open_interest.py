from sqlalchemy import Column
from sqlalchemy import BigInteger
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import DateTime

from sqlalchemy.sql import func

from app.database.sqlserver import Base


class OpenInterest(Base):

    __tablename__ = "open_interest"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String(20), index=True)

    value = Column(Float)

    timestamp = Column(DateTime)

    created_at = Column(DateTime, server_default=func.now())