from unittest.mock import Mock, patch

import pytest

from app.features.feature_service import generate_features
from app.orderflow.orderflow_service import generate_orderflow
from app.smc.smc_service import run_smc_analysis


def test_feature_service_rolls_back_and_closes_on_candle_error():
    fake_db = Mock()

    with patch("app.features.feature_service.SessionLocal", return_value=fake_db), patch(
        "app.features.feature_service.get_latest_candles",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            generate_features("BTCUSDT", "5m")

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_orderflow_service_rolls_back_and_closes_on_candle_error():
    fake_db = Mock()

    with patch("app.orderflow.orderflow_service.SessionLocal", return_value=fake_db), patch(
        "app.orderflow.orderflow_service.get_latest_candles",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            generate_orderflow("BTCUSDT", "5m")

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_smc_service_rolls_back_and_closes_on_candle_error():
    fake_db = Mock()

    with patch("app.smc.smc_service.SessionLocal", return_value=fake_db), patch(
        "app.smc.smc_service.get_latest_candles",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            run_smc_analysis("BTCUSDT", "5m")

    assert fake_db.rollback.called
    assert fake_db.close.called
