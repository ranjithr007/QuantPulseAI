from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.feature_jobs import run_feature_job


def test_feature_job_continues_after_one_timeframe_failure():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT")]

    with patch("app.jobs.feature_jobs.SessionLocal", return_value=fake_db), patch(
        "app.jobs.feature_jobs.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.feature_jobs.generate_features",
        side_effect=[RuntimeError("boom"), {"final_score": 10}],
    ) as generate_features:
        run_feature_job()

    assert generate_features.called
    assert fake_db.close.called


def test_feature_job_suppresses_transient_connection_errors():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT")]

    with patch("app.jobs.feature_jobs.SessionLocal", return_value=fake_db), patch(
        "app.jobs.feature_jobs.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.feature_jobs.generate_features",
        side_effect=ConnectionResetError(
            10054,
            "An existing connection was forcibly closed by the remote host",
            None,
            10054,
            None,
        ),
    ), patch("builtins.print") as print_mock:
        run_feature_job()

    assert fake_db.close.called
    assert not any("Feature job error" in " ".join(str(part) for part in call.args) for call in print_mock.call_args_list)
