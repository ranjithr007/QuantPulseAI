import pytest

from app.api.v1.paper_trade_api import (
    PAPER_PORTFOLIO_DRAWDOWN_LIMIT_PERCENT,
    _official_portfolio_drawdown_blockers,
    _official_portfolio_drawdown_snapshot,
)
from app.api.v1 import paper_trade_api


def test_portfolio_drawdown_below_limit_allows_new_entries():
    wallet = {
        "initial_capital_inr": 200_000,
        "equity_inr": 160_002,
    }

    snapshot = _official_portfolio_drawdown_snapshot(wallet)

    assert snapshot["drawdown_percent"] == 19.999
    assert snapshot["limit_reached"] is False
    assert snapshot["new_entries_paused"] is False
    assert _official_portfolio_drawdown_blockers(wallet) == []


def test_portfolio_drawdown_at_limit_pauses_only_new_entries():
    wallet = {
        "initial_capital_inr": 200_000,
        "equity_inr": 160_000,
    }

    snapshot = _official_portfolio_drawdown_snapshot(wallet)
    blockers = _official_portfolio_drawdown_blockers(wallet)

    assert PAPER_PORTFOLIO_DRAWDOWN_LIMIT_PERCENT == 20.0
    assert snapshot["drawdown_percent"] == 20.0
    assert snapshot["limit_reached"] is True
    assert snapshot["new_entries_paused"] is True
    assert "20.00% portfolio safety limit" in blockers[0]


def test_portfolio_drawdown_fails_closed_without_marked_equity():
    snapshot = _official_portfolio_drawdown_snapshot({})

    assert snapshot["equity_inr"] is None
    assert snapshot["new_entries_paused"] is True
    assert _official_portfolio_drawdown_blockers({}) == [
        "Marked paper equity is unavailable at the entry boundary"
    ]


def test_portfolio_drawdown_ignores_equity_above_initial_capital():
    wallet = {
        "initial_capital_inr": 200_000,
        "equity_inr": 210_000,
    }

    snapshot = _official_portfolio_drawdown_snapshot(wallet)

    assert snapshot["drawdown_percent"] == 0.0
    assert snapshot["new_entries_paused"] is False


@pytest.mark.parametrize(
    ("wallet_equity", "exit_ready", "expected_action"),
    [
        (136_000, True, "skipped_portfolio_drawdown_quarantine"),
        (200_000, False, "skipped_exit_protection_unready"),
    ],
)
def test_final_execution_boundary_enforces_entry_protection(
    monkeypatch,
    wallet_equity,
    exit_ready,
    expected_action,
):
    candidate = {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "eligible": True,
        "blocked_reasons": [],
        "trade_plan": {
            "id": 101,
            "strategy_id": "TREND_PULLBACK",
            "strategy_version": "1",
            "entry_timeframe": "1h",
        },
        "risk_decision": {"confidence": 70},
        "paper_sizing": {"margin_used_inr": 1_000},
    }
    saved = []

    class DummyDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeRepo:
        def acquire_account_execution_lock(self, db):
            pass

        def has_open_trade(self, db, symbol):
            return False

        def risk_snapshot_trades(self, db, *, window_start):
            return []

        def save_candidate(self, db, item):
            saved.append(item)

    monkeypatch.setattr(paper_trade_api, "SessionLocal", DummyDb)
    monkeypatch.setattr(
        paper_trade_api,
        "build_paper_trade_candidates",
        lambda *args, **kwargs: (None, [candidate]),
    )
    monkeypatch.setattr(paper_trade_api, "PaperTradeRepository", FakeRepo)
    monkeypatch.setattr(
        paper_trade_api,
        "resolve_strategy_definition",
        lambda *args, **kwargs: {
            "official_execution_enabled": True,
            "execution_priority": 1,
        },
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_safe_execute_strategy_shadow_candidates",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        paper_trade_api,
        "get_automation_settings",
        lambda db: object(),
    )
    monkeypatch.setattr(
        paper_trade_api,
        "automation_settings_payload",
        lambda row: {
            **paper_trade_api.DEFAULT_AUTOMATION_SETTINGS,
            "enabled": True,
            "locked": False,
        },
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_automation_execution_blockers",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_account_risk_snapshot",
        lambda *args, **kwargs: {
            "risk_available": True,
            "limit_reached": False,
        },
    )
    monkeypatch.setattr(
        paper_trade_api,
        "_paper_wallet_snapshot",
        lambda *args, **kwargs: {
            "initial_capital_inr": 200_000,
            "equity_inr": wallet_equity,
            "remaining_margin_capacity_inr": 100_000,
            "open_position_count": 0,
        },
    )
    monkeypatch.setattr(
        paper_trade_api,
        "exit_protection_snapshot",
        lambda: {
            "policy": "FAST_EXIT_HEARTBEAT_V1",
            "ready": exit_ready,
            "status": "READY" if exit_ready else "BLOCKED",
            "reason": (
                None
                if exit_ready
                else "One-second exit protection heartbeat is stale"
            ),
        },
    )

    result = paper_trade_api.execute_paper_trade_candidates_for_symbol()

    assert saved == []
    assert result["executed_count"] == 0
    skipped = result["skipped"][0]
    assert skipped["action"] == expected_action
    if expected_action == "skipped_portfolio_drawdown_quarantine":
        assert skipped["portfolio_drawdown"] == {
            "policy": "MARKED_EQUITY_DRAWDOWN_V1",
            "initial_capital_inr": 200_000.0,
            "equity_inr": 136_000.0,
            "drawdown_percent": 32.0,
            "limit_percent": 20.0,
            "limit_reached": True,
            "new_entries_paused": True,
        }
    else:
        assert skipped["exit_protection"]["ready"] is False
        assert "stale" in skipped["blocked_reasons"][0]
