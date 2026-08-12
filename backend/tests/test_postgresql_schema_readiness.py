from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from sqlalchemy.schema import CreateTable

from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import Base


def test_all_orm_tables_and_indexes_compile_for_postgresql():
    dialect = postgresql.dialect()

    assert len(Base.metadata.tables) == 40
    for table in Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=dialect))


def test_market_candle_boolean_default_is_valid_postgresql():
    ddl = str(CreateTable(MarketCandle.__table__).compile(dialect=postgresql.dialect()))

    assert "is_final BOOLEAN DEFAULT false NOT NULL" in ddl
    assert "is_final BOOLEAN DEFAULT 0" not in ddl
