from datetime import datetime
from datetime import timedelta
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.point_in_time_snapshots import FeatureSnapshot
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.features.feature_factory import build_features
from app.features.point_in_time_feature_service import PointInTimeLeakageError
from app.features.point_in_time_feature_service import build_decision_snapshot
from app.features.point_in_time_feature_service import build_feature_snapshot
from app.features.point_in_time_feature_service import build_features_as_of
from app.repositories.point_in_time_snapshot_repository import save_feature_snapshot
from app.api.v1.signals_api import build_signal_payload


class Candle:
    def __init__(self, candle_time, open_price, high_price, low_price, close_price, volume=100):
        self.candle_time = candle_time
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price
        self.volume = volume


START = datetime(2026, 1, 1)


def candle(offset, open_price=100, high_price=101, low_price=99, close_price=100, volume=100):
    return Candle(
        START + timedelta(minutes=offset),
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
    )


def test_build_feature_snapshot_uses_chronological_candles():
    candles = [
        candle(2, high_price=105, low_price=99, close_price=104),
        candle(0, high_price=101, low_price=98, close_price=99),
        candle(1, high_price=103, low_price=97, close_price=102),
        candle(3, high_price=106, low_price=100, close_price=105),
    ]

    snapshot = build_feature_snapshot("BTCUSDT", "5m", candles)
    expected = build_features("BTCUSDT", "5m", sorted(candles, key=lambda item: item.candle_time))

    assert snapshot["effective_timestamp"] == candles[-1].candle_time
    assert snapshot["feature"]["final_score"] == expected["final_score"]
    assert snapshot["feature"]["trend"] == expected["trend"]
    assert snapshot["feature"]["quality_score"] == expected["quality_score"]


def test_build_features_as_of_uses_point_in_time_candles():
    candles = [candle(0), candle(1, high_price=103, low_price=98, close_price=102)]
    db = MagicMock()
    as_of = candles[-1].candle_time

    with patch(
        "app.features.point_in_time_feature_service.get_candles_as_of",
        return_value=candles,
    ) as get_candles:
        snapshot = build_features_as_of(db, "ETHUSDT", "5m", as_of, limit=50)

    assert get_candles.called
    assert snapshot["effective_timestamp"] == as_of
    assert snapshot["source_timestamp"] == as_of
    assert snapshot["feature"]["final_score"] == build_features("ETHUSDT", "5m", candles)["final_score"]


def test_save_feature_snapshot_persists_snapshot_contract():
    candles = [candle(0), candle(1, high_price=103, low_price=98, close_price=102)]
    snapshot = build_feature_snapshot("SOLUSDT", "15m", candles)
    db = MagicMock()

    with patch(
        "app.repositories.point_in_time_snapshot_repository._get_existing_feature_snapshot",
        return_value=None,
    ):
        record = save_feature_snapshot(db, snapshot)

    assert record.symbol == "SOLUSDT"
    assert record.timeframe == "15m"
    assert record.feature_version == "feature_factory_v1"
    assert record.effective_timestamp == snapshot["effective_timestamp"]
    assert db.add.called
    assert db.commit.called
    assert db.refresh.called


def test_save_feature_snapshot_creates_missing_table_on_fresh_database():
    engine = create_engine("sqlite:///:memory:")
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    candles = [candle(0), candle(1, high_price=103, low_price=98, close_price=102)]
    snapshot = build_feature_snapshot("ADAUSDT", "5m", candles)

    try:
        record = save_feature_snapshot(db, snapshot)

        assert record.symbol == "ADAUSDT"
        assert db.query(FeatureSnapshot).count() == 1
    finally:
        db.close()


def test_save_feature_snapshot_is_idempotent_for_same_identity():
    engine = create_engine("sqlite:///:memory:")
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    candles = [candle(0), candle(1, high_price=103, low_price=98, close_price=102)]
    snapshot = build_feature_snapshot("BNBUSDT", "15m", candles)

    try:
        first = save_feature_snapshot(db, snapshot)
        second = save_feature_snapshot(db, snapshot)

        assert first.id == second.id
        assert db.query(FeatureSnapshot).count() == 1
    finally:
        db.close()


def test_save_decision_snapshot_is_idempotent_for_same_identity():
    engine = create_engine("sqlite:///:memory:")
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    DecisionSnapshot.__table__.create(bind=engine)
    snapshot = {
        "symbol": "BNBUSDT",
        "timeframe": "15m",
        "source_timestamp": START,
        "effective_timestamp": START,
        "feature_version": "feature_factory_v1",
        "decision_version": "decision_contract_v1",
        "quality_state": "OK",
        "decision": "LONG",
        "confidence": 77.0,
        "regime": "TRENDING_BULL",
        "thesis_id": "42",
    }

    from app.repositories.point_in_time_snapshot_repository import save_decision_snapshot

    try:
        first = save_decision_snapshot(db, snapshot)
        second = save_decision_snapshot(db, snapshot)

        assert first.id == second.id
        assert db.query(DecisionSnapshot).count() == 1
    finally:
        db.close()


def test_build_feature_snapshot_rejects_future_candle_leakage():
    candles = [candle(0), candle(2, high_price=103, low_price=98, close_price=102)]

    with pytest.raises(PointInTimeLeakageError):
        build_feature_snapshot(
            "BNBUSDT",
            "5m",
            candles,
            effective_timestamp=candle(1).candle_time,
        )


def test_build_features_as_of_rejects_future_candle_leakage():
    candles = [candle(0), candle(2, high_price=103, low_price=98, close_price=102)]
    db = MagicMock()

    with patch(
        "app.features.point_in_time_feature_service.get_candles_as_of",
        return_value=candles,
    ):
        with pytest.raises(PointInTimeLeakageError):
            build_features_as_of(db, "XRPUSDT", "15m", candle(1).candle_time, limit=50)


def test_build_decision_snapshot_contract_includes_point_in_time_identity():
    snapshot = build_decision_snapshot(
        "BNBUSDT",
        "15m",
        decision="LONG",
        source_timestamp=START,
        effective_timestamp=START,
        confidence=77.0,
        regime="TRENDING_BULL",
        thesis_id="thesis-1",
        signal={"signal": "LONG", "score": 80},
        trade_plan={"entry": 10.0, "stop_loss": 9.5},
        context={"feature": 1, "regime": 2},
    )

    assert snapshot["symbol"] == "BNBUSDT"
    assert snapshot["timeframe"] == "15m"
    assert snapshot["decision_version"] == "decision_contract_v1"
    assert snapshot["decision"] == "LONG"
    assert snapshot["confidence"] == 77.0
    assert snapshot["regime"] == "TRENDING_BULL"
    assert snapshot["thesis_id"] == "thesis-1"
    assert snapshot["signal"] == {"signal": "LONG", "score": 80}
    assert snapshot["trade_plan"] == {"entry": 10.0, "stop_loss": 9.5}
    assert snapshot["context"] == {"feature": 1, "regime": 2}


def test_build_signal_payload_persists_decision_snapshot():
    db = MagicMock()
    candle = Candle(START, 100, 101, 99, 100)
    feature = MagicMock(Id=11, CreatedAt=START, Trend="BULLISH", ATR=1.5)
    regime = MagicMock(Id=22, CreatedAt=START, Regime="TRENDING_BULL")
    orderflow = MagicMock(Id=33, CreatedAt=START)
    smc = MagicMock(id=44, created_at=START)
    decision_record = MagicMock(id=55, decision_version="decision_contract_v1", effective_timestamp=START)

    with patch("app.api.v1.signals_api.get_latest_candle", return_value=candle), patch(
        "app.api.v1.signals_api.get_ai_inputs",
        return_value={"feature": feature, "regime": regime, "orderflow": orderflow, "smc": smc},
    ), patch(
        "app.api.v1.signals_api.generate_master_signal",
        return_value={"signal": "LONG", "bias": "LONG", "confidence": 80.0, "score": 60, "reasons": ["ok"]},
    ), patch(
        "app.api.v1.signals_api.build_trade_plan",
        return_value={"entry": 100.0, "stop_loss": 99.0, "target1": 102.0, "target2": 103.0},
    ), patch(
        "app.api.v1.signals_api.build_contradiction_report",
        return_value={"status": "OK"},
    ), patch(
        "app.api.v1.signals_api.build_probability_profile",
        return_value={"status": "OK"},
    ), patch(
        "app.api.v1.signals_api._latest_persisted_signal",
        return_value={"latest_usable": None, "latest_ignored": None},
    ), patch(
        "app.api.v1.signals_api.persist_decision_snapshot",
        return_value=decision_record,
    ) as persist_snapshot:
        payload = build_signal_payload(db, "BNBUSDT", "15m", 900)

    assert persist_snapshot.called
    snapshot = persist_snapshot.call_args.args[1]
    assert snapshot["decision"] == "LONG"
    assert snapshot["decision_version"] == "decision_contract_v1"
    assert snapshot["signal"]["score"] == 60
    assert snapshot["trade_plan"]["entry"] == 100.0
    assert payload["decision_snapshot"]["id"] == 55
    assert payload["decision_snapshot"]["decision_version"] == "decision_contract_v1"
