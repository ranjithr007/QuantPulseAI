from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.heatmap_job import run_heatmap_job


def test_heatmap_job_continues_after_one_symbol_error():
    fake_db = SimpleNamespace(close=Mock(), query=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]
    candle = SimpleNamespace(close_price=100.0)

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return candle

    fake_db.query.return_value = FakeQuery()

    with patch("app.jobs.heatmap_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.heatmap_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.heatmap_job.LiquidationHeatmapEngine.analyze",
        side_effect=[RuntimeError("boom"), {"symbol": "ETHUSDT"}],
    ) as analyze, patch(
        "app.jobs.heatmap_job.HeatmapRepository.save"
    ) as save:
        run_heatmap_job()

    assert analyze.called
    assert save.called
    assert fake_db.close.called
