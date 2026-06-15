from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Boolean
from app.database.sqlserver import Base


class Symbol(Base):

    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True, index=True)

    symbol = Column(String(20), unique=True, nullable=False)

    base_asset = Column(String(20))

    quote_asset = Column(String(20))

    is_active = Column(Boolean, default=True)