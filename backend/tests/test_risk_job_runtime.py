from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.risk_job import approve_open_trade_plans
from app.jobs.risk_job import run_risk_job


def test_approve_open_trade_plans_continues_after_one_trade_error():
    db = SimpleNamespace()
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

    with patch(
        "app.jobs.risk_job.TradePlanRepository.get_open_trades",
        return_value=trades,
    ), patch(
        "app.jobs.risk_job.RiskRepository.save",
        side_effect=[RuntimeError("boom"), None],
    ), patch(
        "app.jobs.risk_job.RiskEngine.analyze_trade_plan",
        side_effect=[
            {
                "decision": "APPROVE",
                "reason": None,
                "risk_reward": 2.0,
                "position_size": 1.0,
                "risk_percent": 1.0,
            },
            {
                "decision": "REJECT",
                "reason": "bad setup",
                "risk_reward": 1.0,
                "position_size": 0.0,
                "risk_percent": 1.0,
            },
        ],
    ):
        summary = approve_open_trade_plans(db, Mock(), Mock())

    assert summary["processed"] == 2
    assert summary["rejected"] == 2
    assert len(summary["errors"]) == 2


def test_run_risk_job_continues_after_one_signal_error():
    fake_db = SimpleNamespace(close=Mock())
    signal_ok = SimpleNamespace(symbol="BTCUSDT", timeframe="5m", decision="LONG", confidence=80.0, thesis_id=11)
    signal_bad = SimpleNamespace(symbol="ETHUSDT", timeframe="5m", decision="SHORT", confidence=70.0, thesis_id=22)

    with patch("app.jobs.risk_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.risk_job.FusionSignalRepository.get_latest_signals",
        return_value=[signal_bad, signal_ok],
    ), patch(
        "app.jobs.risk_job.resolve_risk_inputs",
        side_effect=[RuntimeError("bad signal"), {"signal": "LONG", "price": 100.0, "atr": 1.0, "confidence": 80.0}],
    ), patch(
        "app.jobs.risk_job.RiskEngine.analyze",
        return_value={
            "decision": "TAKE_TRADE",
            "reason": None,
            "risk_reward": 2.0,
            "position_size": 1.0,
            "risk_percent": 1.0,
        },
    ), patch(
        "app.jobs.risk_job.RiskRepository.save"
    ) as risk_save, patch(
        "app.jobs.risk_job.approve_open_trade_plans",
        return_value={"processed": 0, "approved": 0, "rejected": 0, "errors": []},
    ) as approve:
        summary = run_risk_job()

    assert summary["processed"] == 2
    assert summary["rejected"] == 1
    assert summary["saved"] == 1
    assert risk_save.called
    assert approve.called
    assert fake_db.close.called
