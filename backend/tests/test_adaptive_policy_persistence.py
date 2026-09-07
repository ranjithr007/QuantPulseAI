from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_strategy_shadow_trading import _candidate, _session
from app.strategies.registry import STRATEGY_REGISTRY
from app.api.v1.paper_trade_api import _rebase_paper_trade_candidate
from app.paper_trading.exit_policy import PAPER_ADAPTIVE_EXIT_POLICY, approved_adaptive_entry_levels
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_shadow_trade_repository import StrategyShadowTradeRepository


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("repository", [PaperTradeRepository, StrategyShadowTradeRepository])
def test_adaptive_reprice_survives_both_ledgers(side, repository):
    candidate = _candidate(next(iter(STRATEGY_REGISTRY.values())), 900)
    candidate["side"] = side
    candidate["trade_plan"].update(side=side, exit_policy=PAPER_ADAPTIVE_EXIT_POLICY, stop_loss=98 if side == "LONG" else 102)
    candidate, error = _rebase_paper_trade_candidate(candidate, {
        "symbol": "BTCUSDT", "mark_price": 110,
        "observed_at": datetime.now(timezone.utc), "source": "TEST_MARK",
    })
    assert error is None
    levels = candidate["execution_exit_levels"]
    db = _session()
    try:
        trade = repository().save_candidate(db, candidate)
        assert trade.exit_policy == PAPER_ADAPTIVE_EXIT_POLICY
        assert trade.entry_price != 100
        assert trade.initial_stop_loss == levels["stop_loss"]
        assert trade.stop_loss == levels["stop_loss"]
        assert trade.target1 == levels["target1"]
        assert trade.target2 == levels["target2"]
        assert trade.target1_fraction == levels["target1_fraction"]
        assert trade.max_hold_hours == levels["max_hold_hours"]
        assert abs(trade.entry_price - trade.stop_loss) / trade.entry_price > .015
        if repository is PaperTradeRepository:
            before = (trade.stop_loss, trade.target1, trade.target2, trade.exit_policy)
            assert repository().ensure_staged_exit_policy(db, trade) is False
            assert before == (trade.stop_loss, trade.target1, trade.target2, trade.exit_policy)
    finally:
        db.close()


def test_incomplete_adaptive_entry_fails_closed():
    candidate = {"trade_plan": {"exit_policy": PAPER_ADAPTIVE_EXIT_POLICY}}
    with pytest.raises(ValueError, match="approved execution"):
        approved_adaptive_entry_levels(candidate, 100)


def test_monitor_does_not_touch_existing_adaptive_trade():
    trade = SimpleNamespace(exit_policy=PAPER_ADAPTIVE_EXIT_POLICY, stop_loss=123)
    db = Mock()
    assert PaperTradeRepository().ensure_staged_exit_policy(db, trade) is False
    assert trade.stop_loss == 123
    assert not db.mock_calls
