from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.bootstrap import DEFAULT_FUTURES_SYMBOLS
from app.database.bootstrap import bootstrap_sqlite_demo_data
from app.database.models.symbols import Symbol


def test_sqlite_bootstrap_creates_schema_and_seeds_futures_symbols():
    engine = create_engine("sqlite:///:memory:")

    bootstrap_sqlite_demo_data(engine)
    bootstrap_sqlite_demo_data(engine)

    with Session(engine) as db:
        records = db.query(Symbol).order_by(Symbol.symbol.asc()).all()

    assert [record.symbol for record in records] == sorted(
        symbol for symbol, _base, _quote in DEFAULT_FUTURES_SYMBOLS
    )
    assert all(record.is_active for record in records)
