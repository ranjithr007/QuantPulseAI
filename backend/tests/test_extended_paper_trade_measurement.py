from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.paper_trade_api import get_paper_trade_measurement
from app.api.v1.signals_api import _persist_ready_watchlist_payload
from app.database.models.paper_trade import PaperTrade
from app.paper_trading.measurement import MeasurementGates
from app.paper_trading.measurement import build_measurement_report


AS_OF = datetime(2026, 6, 23, 12, 0, 0)


def trade(
    pnl_percent,
    *,
    symbol="BTCUSDT",
    side="LONG",
    mode="intraday",
    timeframe="5m",
    regime="TRENDING_BULL",
    confidence=80,
    opened_days_ago=60,
    fees_percent=0.08,
):
    return SimpleNamespace(
        status="CLOSED",
        pnl_percent=pnl_percent,
        symbol=symbol,
        side=side,
        mode=mode,
        entry_timeframe=timeframe,
        regime=regime,
        confidence=confidence,
        opened_at=AS_OF - timedelta(days=opened_days_ago),
        created_at=AS_OF - timedelta(days=opened_days_ago),
        fees_percent=fees_percent,
    )


def gates(**overrides):
    values = {
        "min_closed_trades": 4,
        "min_observation_days": 30,
        "min_profit_factor": 1.25,
        "min_expectancy_percent": 0,
        "min_total_return_percent": 0,
        "max_drawdown_percent": 15,
        "min_cohort_closed_trades": 2,
    }
    values.update(overrides)
    return MeasurementGates(**values)


def test_profitable_history_passes_only_with_sufficient_evidence():
    report = build_measurement_report(
        [trade(3), trade(-1), trade(2), trade(-1)],
        gates=gates(),
        as_of=AS_OF,
    )

    assert report["status"] == "PASS"
    assert report["evaluation"]["evidence_sufficient"] is True
    assert report["overall"]["profit_factor"] == 2.5
    assert report["overall"]["expectancy_percent"] == 0.75
    assert report["overall"]["simulated_fees_percent"] == 0.32
    assert report["policy"]["win_rate_gate"] == "NOT_USED"
    assert report["cohorts"]["symbol"][0]["value"] == "BTCUSDT"
    assert report["cohorts"]["confidence_band"][0]["value"] == "80_PLUS"


def test_good_early_results_remain_insufficient_until_sample_and_duration_gates():
    report = build_measurement_report(
        [trade(3, opened_days_ago=3), trade(2, opened_days_ago=2)],
        gates=gates(),
        as_of=AS_OF,
    )

    assert report["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["evaluation"]["performance_passed"] is True
    assert {item["name"] for item in report["evaluation"]["evidence_checks"] if not item["passed"]} == {
        "closed_trade_sample",
        "observation_period_days",
    }


def test_more_wins_than_losses_still_fails_when_loss_value_is_greater():
    trades = [trade(0.2) for _ in range(6)] + [trade(-1.0) for _ in range(4)]
    report = build_measurement_report(
        trades,
        gates=gates(min_closed_trades=10),
        as_of=AS_OF,
    )

    assert report["overall"]["win_rate"] == 60.0
    assert report["overall"]["net_pnl_percent"] == pytest.approx(-2.8)
    assert report["status"] == "FAIL"
    assert report["evaluation"]["evidence_sufficient"] is True
    assert report["evaluation"]["performance_passed"] is False


def test_cohorts_expose_missing_legacy_context_without_inventing_it():
    legacy = trade(1)
    legacy.mode = None
    legacy.entry_timeframe = None
    legacy.regime = None
    legacy.fees_percent = None

    report = build_measurement_report(
        [legacy],
        gates=gates(min_closed_trades=1),
        as_of=AS_OF,
    )

    assert report["cohorts"]["mode"][0]["value"] == "UNKNOWN"
    assert report["data_quality"]["trades_missing_context"] == {
        "mode": 1,
        "entry_timeframe": 1,
        "regime": 1,
    }
    assert report["data_quality"]["closed_trades_missing_fee_snapshot"] == 1


def test_measurement_gates_reject_invalid_configuration():
    with pytest.raises(ValueError):
        MeasurementGates(min_closed_trades=0)
    with pytest.raises(ValueError):
        MeasurementGates(max_drawdown_percent=0)


def test_measurement_api_exposes_configurable_gate_report():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PaperTrade.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(
            PaperTrade(
                symbol="BTCUSDT",
                side="LONG",
                status="CLOSED",
                pnl_percent=2.0,
                fees_percent=0.08,
                confidence=80,
                mode="intraday",
                entry_timeframe="5m",
                regime="TRENDING_BULL",
                opened_at=AS_OF - timedelta(days=60),
                created_at=AS_OF - timedelta(days=60),
            )
        )
        db.commit()

    with patch("app.api.v1.paper_trade_api.SessionLocal", Session):
        response = get_paper_trade_measurement(
            symbol="btcusdt",
            min_closed_trades=1,
            min_observation_days=1,
            min_profit_factor=1.25,
            min_expectancy_percent=0,
            min_total_return_percent=0,
            max_drawdown_percent=15,
            min_cohort_closed_trades=1,
        )

    assert response["source"] == "extended_paper_trade_measurement"
    assert response["symbol_filter"] == "BTCUSDT"
    assert response["report"]["overall"]["closed_trades"] == 1
    assert response["report"]["gates"]["min_closed_trades"] == 1
    engine.dispose()


def test_ready_trade_plan_snapshots_measurement_context():
    captured = {}

    class Repository:
        def has_open_trade(self, db, symbol, side):
            return False

        def save_ready_trade_plan(self, db, symbol, side, plan, confidence, context=None):
            captured.update(context or {})
            return SimpleNamespace(
                id=7,
                entry_price=plan["entry"],
                stop_loss=plan["stop_loss"],
                target1=plan["target1"],
                target2=plan["target2"],
                risk_reward=plan["risk_reward"],
                confidence=confidence,
            )

    result = _persist_ready_watchlist_payload(
        object(),
        Repository(),
        {
            "symbol": "BTCUSDT",
            "mode": "intraday",
            "timeframes_used": ["5m", "15m", "1h"],
            "trigger": {"status": "READY", "side": "LONG", "reason": "ready"},
            "trade_plan": {
                "entry": 100,
                "stop_loss": 99,
                "target1": 102,
                "target2": 103,
                "risk_reward": 2,
            },
            "trade_plan_validation": {"is_valid": True, "errors": []},
            "timeframes": [
                {
                    "timeframe": "5m",
                    "confidence": 80,
                    "component_scores": {
                        "regime": {"value": "TRENDING_BULL"},
                    },
                }
            ],
        },
    )

    assert result["action"] == "saved"
    assert captured == {
        "mode": "intraday",
        "entry_timeframe": "5m",
        "timeframe_stack": ["5m", "15m", "1h"],
        "regime": "TRENDING_BULL",
    }
