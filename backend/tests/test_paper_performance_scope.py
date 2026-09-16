from app.api.v1 import paper_trade_api


def test_performance_endpoint_uses_only_official_entry_timeframes(monkeypatch):
    captured = {}

    class DummyDb:
        def close(self):
            pass

    class FakeRepo:
        def performance_summary(self, db, **kwargs):
            captured.update(kwargs)
            return {"total_trades": 0}

        def performance_breakdown(self, db, **kwargs):
            captured.update(kwargs)
            return {
                "scope": "ALL_OFFICIAL_CLOSED_TRADES",
                "by_symbol": [],
                "by_side": [],
            }

    class FakeWalletRepo:
        def realized_equity_curve(self, db):
            return {
                "scope": "PAPER_PRODUCTION_REALIZED_LEDGER",
                "event_count": 0,
                "points": [],
            }

    monkeypatch.setattr(paper_trade_api, "SessionLocal", DummyDb)
    monkeypatch.setattr(paper_trade_api, "PaperTradeRepository", FakeRepo)
    monkeypatch.setattr(
        paper_trade_api,
        "PaperWalletLedgerRepository",
        FakeWalletRepo,
    )

    payload = paper_trade_api.get_paper_trade_performance(symbol=None)

    assert captured == {
        "symbol": None,
        "entry_timeframes": tuple(paper_trade_api.PHASE2_OFFICIAL_TIMEFRAMES),
    }
    assert payload["evidence_scope"] == paper_trade_api._phase2_evidence_scope()
    assert payload["breakdown"]["scope"] == "ALL_OFFICIAL_CLOSED_TRADES"
    assert payload["equity_curve"]["scope"] == "PAPER_PRODUCTION_REALIZED_LEDGER"
