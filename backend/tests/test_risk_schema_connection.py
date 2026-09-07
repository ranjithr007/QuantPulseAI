from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.repositories.risk_repository import _table_column_names


def test_risk_schema_inspection_reuses_reserved_session_connection():
    engine = create_engine("sqlite://", poolclass=QueuePool,
                           pool_size=1, max_overflow=0, pool_timeout=.05)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE risk_decisions (id INTEGER, symbol VARCHAR(20))"))
        checkouts = []
        event.listen(engine, "checkout", lambda *args: checkouts.append(True))
        with Session(engine) as db:
            db.execute(text("SELECT 1"))
            transaction = db.get_transaction()
            # An engine-bound inspector would try a second checkout, timeout,
            # then silently substitute nonexistent full ORM columns.
            assert set(_table_column_names(db, "risk_decisions")) == {"id", "symbol"}
            assert db.get_transaction() is transaction
            assert transaction.is_active
            assert checkouts == [True]
    finally:
        engine.dispose()
