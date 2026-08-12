from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.risk_job import RiskJob
from app.jobs.risk_job import run_risk_job
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.risk_job import (
    RiskInputError,
    RiskJob,
    RiskJobConfig,
)


def test_approve_open_trade_plans_continues_after_one_trade_error():
    db = SimpleNamespace(
        commit=Mock(),
        rollback=Mock(),
    )

    trades = [
        SimpleNamespace(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=100.0,
            stop_loss=98.0,
            target1=104.0,
            target2=106.0,
            confidence=80.0,
            thesis_id=1,
        ),
        SimpleNamespace(
            symbol="ETHUSDT",
            side="SHORT",
            entry_price=2000.0,
            stop_loss=2020.0,
            target1=1960.0,
            target2=1940.0,
            confidence=70.0,
            thesis_id=2,
        ),
    ]

    trade_plan_repo = Mock()
    trade_plan_repo.get_open_trades.return_value = trades

    risk_repo = Mock()
    risk_repo.save.side_effect = [
        RuntimeError("boom"),
        None,
    ]

    engine = Mock()
    engine.analyze_trade_plan.side_effect = [
        {
            "decision": "APPROVE",
            "reason": None,
            "risk_reward": 2.0,
            "position_size": 1.0,
            "risk_percent": 0.5,
            "position_tier": "MINIMUM",
        },
        {
            "decision": "REJECT",
            "reason": "bad setup",
            "risk_reward": 1.0,
            "position_size": 0.0,
            "risk_percent": 1.0,
        },
    ]

    job = RiskJob(
        session_factory=Mock(),
        master_repo=Mock(),
        risk_repo=risk_repo,
        trade_plan_repo=trade_plan_repo,
        engine=engine,
    )

    summary = job._approve_trade_plans(db)

    assert summary["processed"] == 2
    assert summary["persisted"] == 1
    assert summary["approved"] == 0
    assert summary["rejected"] == 2
    assert summary["failed"] == 1
    assert len(summary["errors"]) == 2

    trade_plan_repo.get_open_trades.assert_called_once_with(db)
    engine.analyze_trade_plan.assert_called()
    assert engine.analyze_trade_plan.call_count == 2

    assert risk_repo.save.call_count == 2
    assert risk_repo.save.call_args_list[0].args[0]["risk_percent"] == 0.5
    assert risk_repo.save.call_args_list[0].args[0]["position_tier"] == "MINIMUM"
    db.rollback.assert_called_once()
    db.commit.assert_called_once()


def test_approve_open_trade_plans_excludes_legacy_entry_timeframes():
    db = SimpleNamespace(commit=Mock(), rollback=Mock())
    trade_plan_repo = Mock()
    trade_plan_repo.get_open_trades.return_value = [
        SimpleNamespace(
            symbol="XRPUSDT",
            side="SHORT",
            entry_timeframe="5m",
        )
    ]
    engine = Mock()

    job = RiskJob(
        session_factory=Mock(),
        master_repo=Mock(),
        risk_repo=Mock(),
        trade_plan_repo=trade_plan_repo,
        engine=engine,
    )

    summary = job._approve_trade_plans(db)

    assert summary["processed"] == 0
    engine.analyze_trade_plan.assert_not_called()


def test_risk_job_uses_persisted_configured_max_risk_percent():
    settings = SimpleNamespace(max_risk_per_trade=1.5)
    query = Mock()
    query.filter.return_value.first.return_value = settings
    db = SimpleNamespace(query=Mock(return_value=query))
    job = RiskJob(
        config=RiskJobConfig(trade_plan_risk_percent=1.0),
        session_factory=Mock(),
        master_repo=Mock(),
        risk_repo=Mock(),
        trade_plan_repo=Mock(),
        engine=Mock(),
    )

    assert job._configured_max_risk_percent(db) == 1.5


def test_run_risk_job_continues_after_one_signal_error():
    fake_db = Mock()
    session_factory = Mock(return_value=fake_db)

    signal_ok = SimpleNamespace(
        symbol="BTCUSDT",
        timeframe="1h",
        decision="LONG",
        confidence=80.0,
        thesis_id=11,
    )

    signal_bad = SimpleNamespace(
        symbol="ETHUSDT",
        timeframe="1h",
        decision="SHORT",
        confidence=70.0,
        thesis_id=22,
    )

    master_repo = Mock()
    master_repo.get_latest_signals.return_value = [
        signal_bad,
        signal_ok,
    ]

    risk_repo = Mock()

    # Required by RiskJob._already_processed().
    risk_repo.latest_for_symbol.return_value = None

    trade_plan_repo = Mock()

    engine = Mock()
    engine.analyze.return_value = {
        "decision": "TAKE_TRADE",
        "reason": None,
        "entry": 100.0,
        "stop_loss": 99.0,
        "targets": {
            "t1": 102.0,
            "t2": 103.0,
        },
        "risk_reward": 2.0,
        "position_size": 1.0,
        "risk_percent": 1.0,
    }

    job = RiskJob(
        config=RiskJobConfig(
            validate_trade_plans=True,
            skip_duplicate_signals=True,
        ),
        session_factory=session_factory,
        master_repo=master_repo,
        risk_repo=risk_repo,
        trade_plan_repo=trade_plan_repo,
        engine=engine,
    )

    now = datetime.utcnow()

    valid_market_inputs = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "price": 100.0,
        "atr": 1.0,
        "atr_source": "MARKET_FEATURE",
        "candle_timestamp": now,
        "feature_timestamp": now,
    }

    trade_plan_summary = {
        "processed": 0,
        "persisted": 0,
        "approved": 0,
        "rejected": 0,
        "failed": 0,
        "errors": [],
    }

    with patch.object(
        job,
        "_resolve_market_inputs",
        side_effect=[
            RiskInputError("bad signal"),
            valid_market_inputs,
        ],
    ), patch.object(
        job,
        "_approve_trade_plans",
        return_value=trade_plan_summary,
    ) as approve:
        summary = job.run()

    assert summary["processed"] == 2

    # One RiskInputError rejection.
    assert summary["rejected"] == 1

    # One TAKE_TRADE result.
    assert summary["saved"] == 1
    assert summary["approved"] == 1

    # Both the rejection and TAKE_TRADE decision are persisted.
    assert summary["persisted"] == 2

    assert summary["failed"] == 0

    # One rejection plus one approved risk decision.
    assert risk_repo.save.call_count == 2
    assert fake_db.commit.call_count == 2

    engine.analyze.assert_called_once()
    approve.assert_called_once_with(fake_db)
    fake_db.close.assert_called_once()
