from datetime import datetime

import pytest
from sqlalchemy import event, update

from app.database.models.paper_trade import PaperTrade
from app.database.models.paper_wallet_ledger import PaperWalletLedgerEntry
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_shadow_trade_repository import StrategyShadowTradeRepository
from test_strategy_shadow_trading import _session


def _trade(model, symbol="BTCUSDT", **overrides):
    values = dict(symbol=symbol, side="LONG", status="OPEN", entry_price=100,
                  initial_stop_loss=99.25, stop_loss=99.25, target1=101.5,target2=102.3,
                  trade_plan_id=1,risk_decision_id=1,strategy_decision_snapshot_id=1,
                  strategy_id="MARKET_MOVE_EXIT",strategy_version="v1",entry_timeframe="1h",
                  opened_at=datetime.utcnow(),partial_realized_pnl_inr=0)
    return model(**(values | overrides))


def _ledger(key, amount, symbol="BTCUSDT"):
    return PaperWalletLedgerEntry(event_key=key,paper_trade_id=1,symbol=symbol,event_type="TEST_REALIZED",delta_inr=amount)


@pytest.mark.parametrize("repository", [PaperTradeRepository,StrategyShadowTradeRepository])
def test_empty_book_retains_zero_total_row(repository):
    with _session() as db:
        snapshot=repository().valuation_snapshot(db)
        assert snapshot["open_trades"] == []
        assert snapshot["realized_pnl_inr"] == 0
        assert snapshot["valuation_snapshot_version"] == "SINGLE_STATEMENT_V1"


def test_official_snapshot_uses_wallet_ledger_excludes_qa_and_does_not_multiply_total():
    with _session() as db:
        db.add_all([_trade(PaperTrade,"BTCUSDT"),_trade(PaperTrade,"ETHUSDT"),_trade(PaperTrade,"QATEST")])
        db.add_all([_ledger("a",100),_ledger("b",-20),_ledger("qa",999999,"QATEST")])
        db.commit()
        snapshot=PaperTradeRepository().valuation_snapshot(db)
        assert [trade.symbol for trade in snapshot["open_trades"]] == ["BTCUSDT","ETHUSDT"]
        assert snapshot["realized_pnl_inr"] == 80
        assert snapshot["ledger_entry_count"] == 2


def test_shadow_snapshot_is_version_scoped_with_closed_and_partial_cash():
    with _session() as db:
        db.add_all([
            _trade(StrategyShadowTrade,"BTCUSDT",partial_realized_pnl_inr=25),
            _trade(StrategyShadowTrade,"ETHUSDT",status="CLOSED",realized_pnl_inr=-100),
            _trade(StrategyShadowTrade,"SOLUSDT",partial_realized_pnl_inr=12),
            _trade(StrategyShadowTrade,"DOGEUSDT",strategy_version="v2",status="CLOSED",realized_pnl_inr=999),
            _trade(StrategyShadowTrade,"XRPUSDT",strategy_id="CORE_SIGNAL",partial_realized_pnl_inr=555),
            _trade(StrategyShadowTrade,"QATEST",status="CLOSED",realized_pnl_inr=999999),
        ])
        db.commit()
        snapshot=StrategyShadowTradeRepository().valuation_snapshot(db,strategy_id="MARKET_MOVE_EXIT",strategy_version="v1")
        assert [trade.symbol for trade in snapshot["open_trades"]] == ["BTCUSDT","SOLUSDT"]
        assert snapshot["realized_pnl_inr"] == -63


@pytest.mark.parametrize("repository,model", [(PaperTradeRepository,PaperTrade),(StrategyShadowTradeRepository,StrategyShadowTrade)])
def test_newly_closed_trade_cannot_be_counted_as_open_and_realized(repository,model):
    with _session() as db:
        repo=repository()
        repo.ensure_table(db)
        trade=_trade(model)
        db.add(trade);db.commit()
        assert trade.status == "OPEN"
        # Simulate a committed exit becoming visible while the caller retains
        # an old ORM OPEN instance; identity-map caching must not add it back.
        db.execute(update(model).where(model.id==trade.id).values(status="CLOSED",realized_pnl_inr=200)
                   .execution_options(synchronize_session=False))
        if model is PaperTrade:
            db.add(_ledger("new_close",200));db.flush()
        assert trade.status == "OPEN"
        snapshot=repo.valuation_snapshot(db)
        assert snapshot["open_trades"] == []
        assert snapshot["realized_pnl_inr"] == 200


@pytest.mark.parametrize("repository,model", [(PaperTradeRepository,PaperTrade),(StrategyShadowTradeRepository,StrategyShadowTrade)])
def test_snapshot_is_one_data_statement_and_refreshes_partial_state(repository,model,monkeypatch):
    with _session() as db:
        repo=repository();repo.ensure_table(db)
        trade=_trade(model,remaining_position_fraction=1)
        db.add(trade);db.commit()
        assert trade.remaining_position_fraction == 1
        db.execute(update(model).where(model.id==trade.id).values(remaining_position_fraction=.25,partial_realized_pnl_inr=50)
                   .execution_options(synchronize_session=False))
        if model is PaperTrade:
            db.add(_ledger("partial",50));db.flush()
        monkeypatch.setattr(repo,"ensure_table",lambda _db:None)  # Schema was initialized above.
        statements=[]
        def record(_connection,_cursor,statement,_parameters,_context,_many):
            statements.append(statement)
        engine=db.get_bind();event.listen(engine,"before_cursor_execute",record)
        try:
            snapshot=repo.valuation_snapshot(db)
        finally:
            event.remove(engine,"before_cursor_execute",record)
        assert len(statements) == 1
        assert "LEFT OUTER JOIN" in statements[0]
        assert "FOR UPDATE" not in statements[0]
        assert snapshot["open_trades"][0].remaining_position_fraction == .25
        assert snapshot["realized_pnl_inr"] == 50
