from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.trade_plan_job import run_trade_plan_job


def test_trade_plan_job_continues_after_one_signal_error():
    fake_db = SimpleNamespace(close=Mock())
    signals = [
        SimpleNamespace(symbol="BTCUSDT", decision="LONG", confidence=80.0),
        SimpleNamespace(symbol="ETHUSDT", decision="SHORT", confidence=70.0),
    ]
    feature = SimpleNamespace(ATR=1.0)

    with patch("app.jobs.trade_plan_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.trade_plan_job.fusion_repo.get_latest_tradeable_signals",
        return_value=signals,
    ), patch(
        "app.jobs.trade_plan_job.price_service.get_latest_price",
        side_effect=[RuntimeError("bad price"), 100.0],
    ), patch(
        "app.jobs.trade_plan_job.get_latest_feature",
        return_value=feature,
    ), patch(
        "app.jobs.trade_plan_job.planner.create_plan",
        return_value={"symbol": "ETHUSDT", "side": "SHORT"},
    ), patch(
        "app.jobs.trade_plan_job.trade_repo.has_open_trade",
        return_value=False,
    ), patch(
        "app.jobs.trade_plan_job.trade_repo.save_trade_plan"
    ) as save_trade_plan:
        run_trade_plan_job()

    assert save_trade_plan.called
    assert fake_db.close.called
