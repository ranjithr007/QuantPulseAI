from datetime import datetime, timedelta
from types import SimpleNamespace

from app.api.v1 import paper_trade_api


class _DummyDb:
    def rollback(self):
        pass


def _open_trade():
    return SimpleNamespace(
        id=1,
        symbol="BTCUSDT",
        status="OPEN",
        side="LONG",
        entry_price=100.0,
        stop_loss=99.25,
        risk_percent=0.5,
        confidence=49.0,
        fee_bps=7.5,
        position_notional_inr=75_000.0,
        remaining_position_fraction=1.0,
        target1_hit_at=None,
    )


def _settings(monkeypatch):
    monkeypatch.setattr(
        paper_trade_api,
        "get_automation_settings",
        lambda db: object(),
    )
    monkeypatch.setattr(
        paper_trade_api,
        "automation_settings_payload",
        lambda row: {"dailyLossLimit": 4.0},
    )


def test_fresh_final_five_minute_mark_values_open_account_risk(monkeypatch):
    mark = SimpleNamespace(
        close_price=99.0,
        close_time=datetime.utcnow() - timedelta(minutes=5),
        source="BINANCE_MARK_PRICE_KLINES",
    )
    monkeypatch.setattr(
        paper_trade_api,
        "DerivativeRepository",
        lambda: SimpleNamespace(latest_mark_price=lambda *args, **kwargs: mark),
    )
    _settings(monkeypatch)

    snapshot = paper_trade_api._account_risk_snapshot(_DummyDb(), [_open_trade()])

    assert snapshot["risk_available"] is True
    assert snapshot["valuation_complete"] is True
    assert snapshot["current_prices"] == {"BTCUSDT": 99.0}
    assert snapshot["price_evidence"]["BTCUSDT"]["status"] == "FRESH"
    assert snapshot["daily_pnl_percent"] == -0.4312


def test_stale_five_minute_mark_fails_closed_without_entry_fallback(monkeypatch):
    mark = SimpleNamespace(
        close_price=99.0,
        close_time=datetime.utcnow() - timedelta(minutes=16),
        source="BINANCE_MARK_PRICE_KLINES",
    )
    monkeypatch.setattr(
        paper_trade_api,
        "DerivativeRepository",
        lambda: SimpleNamespace(latest_mark_price=lambda *args, **kwargs: mark),
    )
    _settings(monkeypatch)

    snapshot = paper_trade_api._account_risk_snapshot(_DummyDb(), [_open_trade()])

    assert snapshot["risk_available"] is False
    assert snapshot["valuation_complete"] is False
    assert snapshot["current_prices"] == {}
    assert snapshot["price_evidence"]["BTCUSDT"]["status"] == "STALE"
    assert snapshot["contributions"] == []
