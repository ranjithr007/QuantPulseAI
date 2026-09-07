from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError, TimeoutError

from app.api.v1 import paper_trade_api as api


@pytest.mark.parametrize("failure,category", [
    (TimeoutError("pool unavailable"), "DB_POOL_TIMEOUT"),
    (SQLAlchemyError("query unavailable"), "DB_QUERY_FAILED"),
])
def test_failed_history_page_is_unavailable_not_an_empty_success(monkeypatch, failure, category):
    closed = []
    db = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(api, "SessionLocal", lambda: db)

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(api, "PaperTradeRepository", lambda: SimpleNamespace(count_trades=fail))
    response = api.get_paper_trades(status="CLOSED", symbol=None, limit=10, page=4,
                                   official_timeframes_only=True)
    assert response["database_status"] == "UNAVAILABLE"
    assert response["query_complete"] is False
    assert response["page"] == 4
    assert response["error_category"] == category
    assert response["retryable"] is True
    assert "database is not reachable" not in response["message"]
    assert "total_count" not in response  # unknown, not a verified zero
    assert closed == [True]
