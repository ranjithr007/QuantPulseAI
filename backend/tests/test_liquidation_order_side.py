from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.liquidations import Liquidation
from app.engines.liquidation_heatmap_engine import LiquidationHeatmapEngine
from app.intelligence.liquidation_evidence import observed_liquidation_evidence, liquidation_pressure_score
from app.intelligence.contradiction_engine import _direction_from_heatmap
from app.jobs.market_participation_trend_job import _liquidation_context
from app.trading.market_participation_guard import evaluate_market_participation


NOW = datetime(2026, 9, 4, 14, 0)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Liquidation.__table__.create(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def add(db, side, value, *, price=81000, age=60, symbol="BTCUSDT", venue="BINANCE"):
    db.add(Liquidation(symbol=symbol, venue=venue, side=side, price=price,
                       value_usd=value, quantity=value / price, event_time=NOW-timedelta(seconds=age)))
    db.commit()


@pytest.mark.parametrize("side,bias,score", [("SELL", "LONG_LIQUIDATIONS", -100), ("BUY", "SHORT_LIQUIDATIONS", 100)])
def test_side_is_not_inverted_when_price_moves_across_historical_event(db, side, bias, score):
    add(db, side, 100000)
    engine = LiquidationHeatmapEngine()
    for current_price in (79200, 83000):
        result = engine.analyze(db, "BTCUSDT", current_price, as_of_timestamp=NOW)
        assert result["bias"] == bias
        assert result["observed_liquidations"]["imbalance_score"] == score


def test_weighted_imbalance_and_context_do_not_depend_on_heatmap_refresh(db):
    add(db, "SELL", 800000)
    add(db, "BUY", 200000)
    evidence = _liquidation_context(db, "BTCUSDT", as_of_timestamp=NOW)
    assert evidence["status"] == "READY"
    assert evidence["long_liquidation_usd"] == 800000
    assert evidence["short_liquidation_usd"] == 200000
    assert evidence["imbalance_score"] == -60
    assert liquidation_pressure_score(evidence) == -4.8
    assert evidence["source_window_start"] == NOW-timedelta(hours=4)
    assert evidence["source_timestamp"] == NOW-timedelta(seconds=60)


def test_all_events_count_not_only_latest_500_cluster_rows(db):
    db.add_all([Liquidation(symbol="BTCUSDT", venue="BINANCE", side="SELL", price=81000,
                           quantity=1, value_usd=81000, event_time=NOW-timedelta(seconds=1)) for _ in range(510)])
    db.commit()
    evidence = observed_liquidation_evidence(db, "BTCUSDT", as_of_timestamp=NOW)
    assert evidence["source_event_count"] == 510
    assert evidence["long_liquidation_usd"] == 510*81000


def test_window_future_unknown_side_other_coin_and_venue_are_excluded(db):
    add(db, "SELL", 100)
    add(db, "BUY", 10000, age=4*3600+1)
    add(db, "BUY", 10000, age=-1)
    add(db, "UNKNOWN", 10000)
    add(db, "BUY", 10000, symbol="ETHUSDT")
    add(db, "BUY", 10000, venue="OTHER")
    evidence = observed_liquidation_evidence(db, "BTCUSDT", as_of_timestamp=NOW)
    assert evidence["source_event_count"] == 1
    assert evidence["imbalance_score"] == -100


def test_stale_observation_retains_totals_but_cannot_score(db):
    add(db, "BUY", 1000, age=1801)
    evidence = _liquidation_context(db, "BTCUSDT", as_of_timestamp=NOW)
    assert evidence["status"] == "STALE"
    assert evidence["imbalance_score"] is None
    assert evidence["short_liquidation_usd"] == 1000
    assert liquidation_pressure_score(evidence) == 0


def test_no_data_is_unavailable_not_a_synthetic_direction(db):
    evidence = observed_liquidation_evidence(db, "BTCUSDT", as_of_timestamp=NOW)
    assert evidence["status"] == "UNAVAILABLE"
    assert evidence["imbalance_score"] is None
    assert liquidation_pressure_score(evidence) == 0


def test_equal_observed_values_are_neutral(db):
    add(db, "SELL", 100)
    add(db, "BUY", 100)
    evidence = observed_liquidation_evidence(db, "BTCUSDT", as_of_timestamp=NOW)
    assert evidence["bias"] == "NEUTRAL"
    assert evidence["imbalance_score"] == 0


def test_old_hunt_labels_are_not_accepted_as_observed_pressure():
    assert liquidation_pressure_score({"data_quality": "OBSERVED", "bias": "HUNT_SHORTS"}) == 0
    assert _direction_from_heatmap(SimpleNamespace(bias="HUNT_SHORTS")) == "WAIT"
    assert _direction_from_heatmap(SimpleNamespace(bias="LONG_LIQUIDATIONS")) == "SHORT"


def test_unknown_fresh_event_does_not_make_old_known_sides_fresh(db):
    add(db, "SELL", 100, age=1801)
    add(db, "UNKNOWN", 1000, age=1)
    evidence = observed_liquidation_evidence(db, "BTCUSDT", as_of_timestamp=NOW)
    assert evidence["status"] == "STALE"


def test_cached_market_move_score_with_old_liquidations_cannot_authorize_entry():
    payload = {"status": "READY", "quality_state": "OK", "direction": "BULLISH",
               "confidence": 60, "score": 60, "effective_timestamp": NOW,
               "components": {"liquidation": 8},
               "liquidation": {"bias": "HUNT_SHORTS", "data_quality": "OBSERVED"}}
    decision = evaluate_market_participation(payload, "LONG", as_of_timestamp=NOW)
    assert decision["allowed"] is False
    assert decision["status"] == "LEGACY_LIQUIDATION_EVIDENCE"
