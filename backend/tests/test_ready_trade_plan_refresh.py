from types import SimpleNamespace

from app.api.v1.signals_api import _persist_ready_watchlist_payload


def _ready_payload():
    return {
        "symbol": "DOGEUSDT",
        "trigger": {
            "status": "READY",
            "side": "LONG",
            "reason": "Timing aligned",
            "conditions": [],
        },
        "trade_plan": {
            "entry": 0.10,
            "stop_loss": 0.09,
            "target1": 0.12,
            "target2": 0.13,
            "risk_reward": 2.0,
        },
        "trade_plan_validation": {
            "is_valid": True,
            "errors": [],
        },
        "timeframes": [
            {
                "timeframe": "1h",
                "confidence": 72,
                "component_scores": {
                    "regime": {"value": "BULLISH"},
                },
            }
        ],
        "timeframes_used": ["1h", "2h", "4h", "1d"],
        "mode": "intraday",
    }


class FakeTradeRepo:
    def __init__(self, existing_trade=None):
        self.existing_trade = existing_trade
        self.invalidated = []
        self.saved = []

    def get_open_trade(self, db, symbol, side):
        return self.existing_trade

    def invalidate_trade(self, db, trade, reason):
        self.invalidated.append((trade.id, reason))
        return trade

    def save_ready_trade_plan(self, db, symbol, side, plan, confidence, context=None):
        trade = SimpleNamespace(
            id=99,
            entry_price=plan["entry"],
            stop_loss=plan["stop_loss"],
            target1=plan["target1"],
            target2=plan.get("target2"),
            risk_reward=plan["risk_reward"],
            confidence=confidence,
        )
        self.saved.append((symbol, side, plan, confidence, context))
        return trade


def test_persist_ready_payload_replaces_stale_open_trade_plan():
    repo = FakeTradeRepo(
        existing_trade=SimpleNamespace(
            id=7,
            entry_price=0.099,
            stop_loss=0.09,
            target1=0.12,
            target2=0.13,
            risk_reward=2.0,
            confidence=70,
        )
    )

    result = _persist_ready_watchlist_payload(
        db=None,
        trade_repo=repo,
        payload=_ready_payload(),
    )

    assert result["action"] == "replaced_existing_open"
    assert result["replaced_trade_plan_id"] == 7
    assert repo.invalidated == [(7, "Open trade plan replaced by newer READY signal")]
    assert len(repo.saved) == 1


def test_persist_ready_payload_keeps_existing_matching_open_trade_plan():
    repo = FakeTradeRepo(
        existing_trade=SimpleNamespace(
            id=7,
            entry_price=0.10,
            stop_loss=0.09,
            target1=0.12,
            target2=0.13,
            risk_reward=2.0,
            confidence=72,
        )
    )

    result = _persist_ready_watchlist_payload(
        db=None,
        trade_repo=repo,
        payload=_ready_payload(),
    )

    assert result["action"] == "skipped_existing_open"
    assert repo.invalidated == []
    assert repo.saved == []
