from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import paper_trade_api
from app.api.v1.paper_trade_api import _official_timeframe_records
from app.database.models.paper_trade import PaperTrade
from app.database.models.paper_wallet_ledger import PaperWalletLedgerEntry
from app.paper_trading.evidence_scope import is_quarantined_paper_trade
from app.paper_trading.evidence_scope import production_paper_trade_records
from app.paper_trading.inr_sizing import build_inr_paper_wallet
from app.paper_trading.paper_trade_performance import paper_trade_performance
from app.paper_trading.reentry_policy import same_side_stop_reentry_cooldown
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.paper_wallet_ledger_repository import PaperWalletLedgerRepository
from app.risk.account_risk import build_account_daily_pnl_snapshot


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _trade(symbol, **overrides):
    values = {
        "id": 1,
        "symbol": symbol,
        "status": "CLOSED",
        "side": "LONG",
        "entry_timeframe": "1h",
        "entry_price": 100.0,
        "stop_loss": 99.25,
        "exit_price": 99.25,
        "pnl_percent": -1.0,
        "result": "LOSS",
        "confidence": 50.0,
        "fee_bps": 7.5,
        "risk_percent": 0.5,
        "closed_at": NOW - timedelta(hours=1),
        "opened_at": NOW - timedelta(hours=2),
        "exit_reason": "STOP",
        "remaining_position_fraction": 1.0,
        "position_notional_inr": 75_000.0,
        "margin_used_inr": 15_000.0,
        "realized_pnl_inr": -750.0,
        "partial_realized_pnl_inr": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_scope_quarantines_qa_symbols_but_keeps_real_coin_trades():
    qa = _trade("QACLOSED0USDT")
    real = _trade("BTCUSDT", id=2)

    assert is_quarantined_paper_trade(qa) is True
    assert production_paper_trade_records([qa, real]) == [real]
    assert _official_timeframe_records([qa, real]) == [real]


def test_repository_excludes_qa_rows_by_default_but_preserves_audit_access():
    engine = create_engine("sqlite:///:memory:")
    PaperTrade.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    repo = PaperTradeRepository()

    with Session() as db:
        db.add_all(
            [
                PaperTrade(symbol="QAOPEN0USDT", status="OPEN", entry_timeframe="1h"),
                PaperTrade(symbol="QACLOSED0USDT", status="CLOSED", entry_timeframe="1h"),
                PaperTrade(symbol="BTCUSDT", status="OPEN", entry_timeframe="1h"),
                PaperTrade(symbol="ETHUSDT", status="CLOSED", entry_timeframe="4h"),
            ]
        )
        db.commit()

        assert [trade.symbol for trade in repo.all_trades(db)] == [
            "BTCUSDT",
            "ETHUSDT",
        ]
        assert [trade.symbol for trade in repo.get_open_trades(db)] == ["BTCUSDT"]
        assert len(repo.all_trades(db, include_quarantined=True)) == 4

    engine.dispose()


def test_bundle_reports_quarantined_count_without_exposing_qa_rows(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    PaperTrade.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(
        paper_trade_api,
        "_account_risk_snapshot",
        lambda _db, _trades: {"limit_reached": False},
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_wallet_snapshot",
        lambda _db, _trades, account_risk=None: {"open_position_count": 0},
    )

    with Session() as db:
        db.add_all(
            [
                PaperTrade(symbol="QACLOSED0USDT", status="CLOSED", entry_timeframe="1h"),
                PaperTrade(symbol="BTCUSDT", status="CLOSED", entry_timeframe="1h"),
            ]
        )
        db.commit()

        bundle = paper_trade_api.build_paper_trade_bundle(
            db,
            open_limit=None,
            closed_limit=None,
        )

    assert bundle["closedTrades"]["count"] == 1
    assert bundle["closedTrades"]["records"][0]["symbol"] == "BTCUSDT"
    assert bundle["ledgerScope"] == {
        "scope": "PAPER_PRODUCTION",
        "policy": "QA_SYMBOL_QUARANTINE_V1",
        "visible_records": 1,
        "quarantined_records": 1,
        "auditable_records": 2,
    }
    engine.dispose()


def test_qa_losses_do_not_affect_performance_or_account_daily_loss():
    qa_loss = _trade("QACLOSED0USDT", realized_pnl_inr=-10_000.0)
    real_win = _trade(
        "BTCUSDT",
        id=2,
        result="WIN",
        pnl_percent=1.0,
        realized_pnl_inr=750.0,
    )

    performance = paper_trade_performance([qa_loss, real_win])
    account = build_account_daily_pnl_snapshot(
        [qa_loss, real_win],
        daily_loss_limit=4.0,
        as_of=NOW,
    )

    assert performance["total_trades"] == 1
    assert performance["wins"] == 1
    assert performance["losses"] == 0
    assert account["daily_pnl_percent"] == 0.75
    assert account["limit_reached"] is False
    assert [item["symbol"] for item in account["contributions"]] == ["BTCUSDT"]


def test_qa_open_positions_and_wallet_events_do_not_consume_real_capacity():
    qa_open = _trade("QAOPEN0USDT", status="OPEN", closed_at=None)
    real_open = _trade("BTCUSDT", id=2, status="OPEN", closed_at=None)
    ledger_entries = [
        SimpleNamespace(
            id=1,
            event_key="qa:loss",
            paper_trade_id=1,
            symbol="QACLOSED0USDT",
            event_type="FINAL_CLOSE_REALIZED",
            delta_inr=-10_000.0,
            position_fraction=1.0,
            created_at=NOW,
        ),
        SimpleNamespace(
            id=2,
            event_key="btc:win",
            paper_trade_id=2,
            symbol="BTCUSDT",
            event_type="FINAL_CLOSE_REALIZED",
            delta_inr=500.0,
            position_fraction=1.0,
            created_at=NOW,
        ),
    ]

    wallet = build_inr_paper_wallet(
        [qa_open, real_open],
        ledger_entries=ledger_entries,
        current_prices={"BTCUSDT": 100.0},
    )

    assert wallet["open_position_count"] == 1
    assert [item["symbol"] for item in wallet["positions"]] == ["BTCUSDT"]
    assert wallet["realized_pnl_inr"] == 500.0
    assert wallet["ledger_entry_count"] == 1


def test_qa_stop_does_not_start_real_coin_reentry_cooldown():
    qa_stop = _trade("QACLOSED0USDT")

    cooldown = same_side_stop_reentry_cooldown(
        [qa_stop],
        "QACLOSED0USDT",
        "LONG",
        now=NOW,
    )

    assert cooldown["active"] is False


def test_wallet_ledger_repository_quarantines_qa_events_by_default():
    engine = create_engine("sqlite:///:memory:")
    PaperWalletLedgerEntry.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)
    repo = PaperWalletLedgerRepository()

    with Session() as db:
        db.add_all(
            [
                PaperWalletLedgerEntry(
                    event_key="qa:1",
                    paper_trade_id=1,
                    symbol="QAOPEN0USDT",
                    event_type="ENTRY",
                ),
                PaperWalletLedgerEntry(
                    event_key="btc:1",
                    paper_trade_id=2,
                    symbol="BTCUSDT",
                    event_type="ENTRY",
                ),
            ]
        )
        db.commit()

        assert [item.symbol for item in repo.list_entries(db)] == ["BTCUSDT"]
        assert len(repo.list_entries(db, include_quarantined=True)) == 2

    engine.dispose()
