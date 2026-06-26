from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.heatmap_job import run_heatmap_job


def test_heatmap_job_suppresses_transient_connection_errors():
    fake_db = Mock()
    fake_candle = SimpleNamespace(close_price=1.23)
    symbol = SimpleNamespace(symbol="BTCUSDT")

    fake_query = Mock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = fake_query
    fake_query.first.return_value = fake_candle
    fake_db.query.return_value = fake_query

    with patch("app.jobs.heatmap_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.heatmap_job.SymbolRepository.get_active_symbols",
        return_value=[symbol],
    ), patch(
        "app.jobs.heatmap_job.LiquidationHeatmapEngine.analyze",
        side_effect=ConnectionResetError(
            10054,
            "An existing connection was forcibly closed by the remote host",
            None,
            10054,
            None,
        ),
    ), patch("builtins.print") as print_mock:
        run_heatmap_job()

    assert fake_db.close.called
    assert not any(
        "Heatmap job error" in " ".join(str(part) for part in call.args)
        for call in print_mock.call_args_list
    )
