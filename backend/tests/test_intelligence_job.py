from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.intelligence_job import run_intelligence_job


def test_intelligence_job_suppresses_transient_connection_errors():
    fake_db = SimpleNamespace(close=Mock(), rollback=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT")]

    with patch("app.jobs.intelligence_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.intelligence_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.intelligence_job.MarketFeatureBuilder.build",
        side_effect=ConnectionResetError(
            10054,
            "An existing connection was forcibly closed by the remote host",
            None,
            10054,
            None,
        ),
    ), patch("builtins.print") as print_mock:
        run_intelligence_job()

    assert fake_db.rollback.called is False
    assert fake_db.close.called
    assert not any(
        "Intelligence job error" in " ".join(str(part) for part in call.args)
        for call in print_mock.call_args_list
    )
