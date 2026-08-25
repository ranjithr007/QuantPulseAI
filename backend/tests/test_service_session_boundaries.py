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


def test_orderflow_service_reads_cvd_through_repository_instance_and_saves():
    fake_db = Mock()
    candles = [Mock() for _ in range(20)]
    analyzed = {
        "buy_volume": 12.0,
        "sell_volume": 8.0,
        "delta": 4.0,
        "cumulative_delta": 19.0,
        "buyer_strength": 60.0,
        "seller_strength": 40.0,
        "absorption": "NONE",
        "exhaustion": "NONE",
        "signal": "BUYERS_CONTROL",
        "confidence": 50.0,
    }

    with patch(
        "app.orderflow.orderflow_service.SessionLocal",
        return_value=fake_db,
    ), patch(
        "app.orderflow.orderflow_service.get_latest_candles",
        return_value=candles,
    ), patch(
        "app.orderflow.orderflow_service.OrderFlowRepository.get_last_cvd",
        autospec=True,
        return_value=15.0,
    ) as get_last_cvd, patch(
        "app.orderflow.orderflow_service.analyze_orderflow",
        return_value=analyzed,
    ) as analyze, patch(
        "app.orderflow.orderflow_service.OrderFlowRepository.save_orderflow",
    ) as save:
        result = generate_orderflow("BTCUSDT", "1h")

    repository, called_db, called_symbol = get_last_cvd.call_args.args
    assert repository.__class__.__name__ == "OrderFlowRepository"
    assert called_db is fake_db
    assert called_symbol == "BTCUSDT"
    analyze.assert_called_once_with(candles, 15.0, True)
    save.assert_called_once_with(fake_db, "BTCUSDT", "1h", analyzed)
    assert result == analyzed
    assert fake_db.rollback.called is False
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
