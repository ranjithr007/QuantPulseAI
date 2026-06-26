from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.ai_signal_job import run_ai_signal_job


def test_ai_signal_job_closes_db_when_save_fails():
    fake_db = SimpleNamespace(close=Mock(), rollback=Mock(), query=Mock())
    liquidity = SimpleNamespace(
        symbol="BTCUSDT",
        long_squeeze_probability=10,
        short_squeeze_probability=90,
    )
    heatmap = SimpleNamespace(
        bias="HUNT_SHORTS",
        current_price=65000.0,
        target_price=64000.0,
    )

    liquidity_query = Mock()
    liquidity_query.order_by.return_value.first.return_value = liquidity
    heatmap_query = Mock()
    heatmap_query.order_by.return_value.first.return_value = heatmap

    fake_db.query.side_effect = [liquidity_query, heatmap_query]

    with patch("app.jobs.ai_signal_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.ai_signal_job.AISignalRepository.save",
        side_effect=RuntimeError("boom"),
    ):
        run_ai_signal_job()

    assert fake_db.close.called
