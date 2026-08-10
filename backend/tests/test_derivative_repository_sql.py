from sqlalchemy import true
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import Query

from app.database.models.futures_mark_prices import FuturesMarkPrice


def test_final_mark_price_predicate_compiles_for_sql_server():
    statement = Query(FuturesMarkPrice).filter(
        FuturesMarkPrice.is_final == true()
    ).statement
    sql = str(
        statement.compile(
            dialect=mssql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "is_final = 1" in sql
    assert "is_final IS 1" not in sql
