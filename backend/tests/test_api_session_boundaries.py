from unittest.mock import Mock, patch

import pytest

from app.api.v1.ai_scores_api import get_ai_scores
from app.api.v1.indicators_api import get_indicators
from app.api.v1.market_api import get_market_candles


def test_market_api_rolls_back_and_closes_on_error():
    fake_db = Mock()

    with patch("app.api.v1.market_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.market_api.build_market_candles_payload",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            get_market_candles("BTCUSDT")

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_ai_scores_api_rolls_back_and_closes_on_error():
    fake_db = Mock()

    with patch("app.api.v1.ai_scores_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.ai_scores_api.build_ai_scores_payload",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            get_ai_scores("BTCUSDT")

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_indicators_api_rolls_back_and_closes_on_error():
    fake_db = Mock()

    with patch("app.api.v1.indicators_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.indicators_api.get_latest_candles",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            get_indicators("BTCUSDT")

    assert fake_db.rollback.called
    assert fake_db.close.called
