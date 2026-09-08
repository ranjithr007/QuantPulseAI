import json
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from app.backtesting.strategy_comparison import _decision, _open, replay_version, CAPITAL
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit

START = datetime(2026, 9, 1, 0, 5)


def decision(**overrides):
    result = dict(time=START-timedelta(seconds=1), id=1, timeframe="1h", decision="ELIGIBLE", side="LONG", confidence=65,
                  plan=dict(entry=100, stop_loss=99.25, target1=101.5, target2=102.3,
                            exit_policy="PAPER_STAGED_EXIT_V2", target1_fraction=.75, max_hold_hours=48))
    result.update(overrides)
    return result


def bar(offset=0, **overrides):
    opened = START + timedelta(minutes=offset)
    result = dict(symbol="ETHUSDT", open_time=opened, close_time=opened+timedelta(minutes=5),
                  candle_time=opened, open_price=100, high_price=100.1, low_price=99.9, close_price=100)
    result.update(overrides)
    return NS(**result)


def test_entry_is_next_bar_and_rebased_to_actual_fill():
    trade = _open(decision(), bar(open_price=200), CAPITAL)
    assert trade.trailing_activation_r is None
    assert trade.entry_price > 200
    assert trade.stop_loss / trade.entry_price == pytest.approx(.9925)
    assert trade.target2 / trade.entry_price == pytest.approx(1.023)
    result = replay_version([decision(time=START)], [bar(low_price=98)])
    assert result["closed_trades"] == result["open_positions"] == 0


def test_stop_first_collision_and_costs():
    result = replay_version([decision()], [bar(high_price=104, low_price=98)])
    assert result["closed_trades"] == result["stop_exits"] == 1
    assert result["target1_hits"] == 0
    assert result["pnl_inr"] < -CAPITAL*.85*.0075


def test_two_targets_settle_both_fractions_once():
    result = replay_version([decision()], [bar(high_price=104, close_price=103)])
    assert result["target1_hits"] == result["target2_exits"] == 1
    assert result["wins"] == 1
    # Weighted 75% T1 / 25% T2 gross = 1.7%, then fees/slippage.
    assert 0 < result["pnl_inr"] < CAPITAL*.85*.017
    assert result["open_positions"] == 0


def test_missing_exit_candles_censor_not_invent_a_fill():
    result = replay_version([decision()], [bar(), bar(15, high_price=104)])
    assert result["censored_positions"] == 1
    assert result["closed_trades"] == 0


def test_wait_overrides_eligible_in_same_timeframe():
    result = replay_version([decision(), decision(id=2, time=START-timedelta(microseconds=1), decision="WAIT")], [bar(low_price=98)])
    assert result["closed_trades"] == 0


def test_one_position_across_timeframes_and_no_unchanged_reentry():
    result = replay_version([decision(), decision(id=2, timeframe="4h")], [bar(high_price=104), bar(5, high_price=104)])
    assert result["closed_trades"] == 1


def test_same_direction_cooldown_but_opposite_allowed():
    fresh_time = START+timedelta(minutes=5, seconds=1)
    long = decision(id=2, time=fresh_time)
    short = decision(id=3, time=fresh_time, side="SHORT", timeframe="2h",
                     plan=dict(entry=100, stop_loss=100.75, target1=98.5, target2=97.7,
                               exit_policy="PAPER_STAGED_EXIT_V2", target1_fraction=.75, max_hold_hours=48))
    result = replay_version([decision(), long, short], [bar(low_price=98), bar(5), bar(10, low_price=96)])
    assert [trade["side"] for trade in result["trades"]] == ["LONG", "SHORT"]


def test_stale_decision_and_missing_policy_not_executed():
    assert replay_version([decision(time=START-timedelta(minutes=11))], [bar()])["open_positions"] == 0
    invalid = decision()
    invalid["plan"].pop("exit_policy")
    result = replay_version([invalid], [bar()])
    assert result["open_positions"] == 0
    assert result["skipped"]["unsupported_or_invalid_recorded_plan"] == 1


def test_snapshot_uses_recording_time_not_just_effective_time():
    recorded = START+timedelta(hours=1)
    row = NS(snapshot_json=json.dumps({"context": {"side": "LONG"}, "trade_plan": {}}),
             effective_timestamp=START, source_timestamp=START, created_at=recorded,
             timeframe="1h", decision="ELIGIBLE", confidence=60, id=1)
    assert _decision(row)["time"] == recorded


@pytest.mark.parametrize("location", ["plan", "context", "plan_evidence", "context_evidence"])
def test_recorded_trailing_activation_survives_snapshot_decode(location):
    snapshot = {"trade_plan": decision()["plan"], "context": {"side": "LONG"}}
    if location.endswith("_evidence"):
        target = snapshot["trade_plan" if location.startswith("plan") else "context"].setdefault("execution_evidence", {})
    else:
        target = snapshot["trade_plan" if location == "plan" else "context"]
    target["trailing_activation_r"] = 1
    row = NS(snapshot_json=json.dumps(snapshot), effective_timestamp=START, source_timestamp=START,
             created_at=START, timeframe="1h", decision="ELIGIBLE", confidence=65, id=1)
    assert _open(_decision(row), bar(), CAPITAL).trailing_activation_r == 1


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("activation,expected", [(None, "MOVE_STOP"), (0, "MOVE_STOP"), (1, "HOLD")])
def test_replay_keeps_delayed_trail_inactive_below_one_r_and_legacy_immediate(side, activation, expected):
    item = decision(side=side)
    if side == "SHORT":
        item["plan"].update(stop_loss=100.75, target1=98.5, target2=97.7)
    item["plan"]["trailing_activation_r"] = activation
    trade = _open(item, bar(), CAPITAL)
    assert trade.trailing_activation_r == activation
    sign = 1 if side == "LONG" else -1
    risk = abs(trade.entry_price-trade.initial_stop_loss)
    close = trade.entry_price + sign * risk * .5
    candle = bar(high_price=max(close, trade.entry_price), low_price=min(close, trade.entry_price), close_price=close)
    assert evaluate_paper_trade_exit(trade, candle)["action"] == expected
    close = trade.entry_price + sign * risk * 1.01
    candle = bar(high_price=max(close, trade.entry_price), low_price=min(close, trade.entry_price), close_price=close)
    assert evaluate_paper_trade_exit(trade, candle)["action"] == "MOVE_STOP"


@pytest.mark.parametrize("activation", [True, -1, 6, "", "oops", float("inf"), float("nan")])
def test_invalid_recorded_activation_does_not_silently_use_immediate_trailing(activation):
    item = decision(trailing_activation_r=activation)
    assert _open(item, bar(), CAPITAL) is None


@pytest.mark.parametrize("profile,activation", [("DELAYED_TRAIL_1R_V1", None), ("DELAYED_TRAIL_1R_V1", 0),
                                               ("IMMEDIATE_TRAIL_V1", None), ("IMMEDIATE_TRAIL_V1", 1)])
def test_named_exit_experiment_requires_recorded_matching_threshold(profile, activation):
    item = decision(trailing_activation_r=activation, execution_evidence={"exit_management_profile": profile})
    assert _open(item, bar(), CAPITAL) is None


def test_conflicting_activation_is_not_resolved_by_silent_precedence():
    item = decision(trailing_activation_r=1)
    item["plan"]["trailing_activation_r"] = 0
    assert _open(item, bar(), CAPITAL) is None


def test_closed_replay_trade_reports_recorded_activation_without_inventing_legacy_evidence():
    for activation in (None, 0, 1):
        profile = None if activation is None else "IMMEDIATE_TRAIL_V1" if activation == 0 else "DELAYED_TRAIL_1R_V1"
        item = decision(trailing_activation_r=activation, execution_evidence={"exit_management_profile": profile})
        result = replay_version([item], [bar(high_price=104, close_price=103)])
        assert result["trades"][0]["trailing_activation_r"] == activation
        assert result["trades"][0]["exit_management_profile"] == profile


def test_delayed_replay_does_not_take_a_pre_activation_trailing_exit():
    bars = [bar(high_price=100.5, close_price=100.4), bar(5, low_price=99.5)]
    immediate = replay_version([decision(trailing_activation_r=0)], bars)
    legacy = replay_version([decision()], bars)
    delayed = replay_version([decision(trailing_activation_r=1)], bars)
    assert immediate["stop_exits"] == legacy["stop_exits"] == 1
    assert delayed["closed_trades"] == 0
    assert delayed["open_positions"] == 1


def test_gap_stop_uses_worse_open_and_hold_window_not_closed_artificially():
    result = replay_version([decision()], [bar(), bar(5, open_price=95, high_price=96, low_price=94, close_price=95)])
    assert result["trades"][0]["exit"] < 95
    assert replay_version([decision()], [bar()])["open_positions"] == 1


def test_timeout_with_target1_closes_remainder():
    item = decision()
    item["plan"]["max_hold_hours"] = 5/60
    result = replay_version([item], [bar(high_price=102, close_price=101.8)])
    assert result["closed_trades"] == 1
    assert result["trades"][0]["reason"] == "TIME_EXIT"


def test_database_report_separates_versions_and_rejects_missing_lineage(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.backtesting import strategy_comparison as module
    from app.database.models.market_candles import MarketCandle
    from app.database.models.point_in_time_snapshots import DecisionSnapshot
    from app.database.models.pipeline_runs import PipelineRun
    from app.database.sqlserver import Base
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[MarketCandle.__table__, DecisionSnapshot.__table__, PipelineRun.__table__])
    monkeypatch.setattr(module, "strategy_definitions", lambda db: [dict(id="A", version="v1", name="A"), dict(id="B", version="v1", name="B")])
    with Session(engine) as db:
        db.add(PipelineRun(id="run", generation_id="generation", status="COMPLETED", started_at=START-timedelta(minutes=1), completed_at=START-timedelta(seconds=1)))
        for index, version in enumerate(("v1", "v2", "unproven"), 1):
            db.add(DecisionSnapshot(id=index, symbol="ETHUSDT", timeframe="1h", source_timestamp=START-timedelta(minutes=1),
                                    effective_timestamp=START-timedelta(minutes=1), created_at=START-timedelta(minutes=1),
                                    feature_version="v1", decision_version=version, strategy_id="A", strategy_version=version,
                                    data_generation_id="generation" if version != "unproven" else None,
                                    quality_state="OK", decision="ELIGIBLE", confidence=65,
                                    snapshot_json=json.dumps({"trade_plan": decision()["plan"], "context": {"side": "LONG"}})))
        values = vars(bar(high_price=104, close_price=103))
        db.add(MarketCandle(id=1, timeframe="5m", venue="BINANCE", market_type="FUTURES", is_final=True, quality_state="VERIFIED", **values))
        db.commit()
        report = module.build_strategy_comparison(db, "ETHUSDT", 1, START+timedelta(hours=1))
        results = {(item["strategy_id"], item["version"]): item for item in report["results"]}
        assert results[("A", "v1")]["closed_trades"] == results[("A", "v2")]["closed_trades"] == 1
        assert results[("A", "v1")]["pnl_inr"] == results[("A", "v2")]["pnl_inr"]
        assert results[("B", "v1")]["status"] == "NO_DECISION_HISTORY"
        assert results[("A", "unproven")]["status"] == "NO_REPLAYABLE_DECISIONS"
        assert report["replay_policy_version"] == module.REPLAY_POLICY_VERSION == "recorded_exit_policy_v2"
        assert any("Entry structure" in limitation and "NOT revalidated" in limitation for limitation in report["limitations"])
        assert any("Missing legacy activation" in limitation for limitation in report["limitations"])
        assert not db.new and not db.dirty and not db.deleted


def test_api_uses_durable_worker_queue_and_caches_results(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.api.v1 import backtest_api
    from app.backtesting import strategy_comparison, walk_forward_jobs
    from app.database.models.walk_forward_jobs import WalkForwardJob
    from app.database.sqlserver import Base
    engine = create_engine(f"sqlite:///{tmp_path / 'comparison.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[WalkForwardJob.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(walk_forward_jobs, "SessionLocal", factory)
    monkeypatch.setattr(backtest_api, "SessionLocal", factory)
    monkeypatch.setattr(backtest_api, "get_settings", lambda: NS(process_role="api"))
    calls = []
    def compare(db, symbol, days):
        calls.append((symbol, days))
        return {"source": strategy_comparison.ENGINE, "results": []}
    monkeypatch.setattr(strategy_comparison, "build_strategy_comparison", compare)
    app = FastAPI()
    app.include_router(backtest_api.router)
    client = TestClient(app)
    response = client.post("/backtest/strategy-comparison/jobs?symbol=ETHUSDT&days=7")
    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    assert not calls
    queued = walk_forward_jobs.claim_next_walk_forward_job()
    assert queued["parameters"] == {
        "engine": strategy_comparison.ENGINE, "symbol": "ETHUSDT", "days": 7,
        "replay_policy_version": strategy_comparison.REPLAY_POLICY_VERSION,
    }
    backtest_api._run_walk_forward_validation_job(queued["job_id"], queued["parameters"])
    completed = client.get(f'/backtest/walk-forward/jobs/{queued["job_id"]}').json()
    assert completed["status"] == "COMPLETED"
    assert calls == [("ETHUSDT", 7)]
    cached = client.post("/backtest/strategy-comparison/jobs?symbol=ETHUSDT&days=7").json()
    assert cached["job_id"] == completed["job_id"]
    assert cached["status"] == "COMPLETED"
    monkeypatch.setattr(strategy_comparison, "REPLAY_POLICY_VERSION", "recorded_exit_policy_test_next")
    updated = client.post("/backtest/strategy-comparison/jobs?symbol=ETHUSDT&days=7").json()
    assert updated["job_id"] != cached["job_id"]
    assert updated["status"] == "QUEUED"
    assert calls == [("ETHUSDT", 7)]
    assert client.post("/backtest/strategy-comparison/jobs?symbol=ETHUSDT&days=365").status_code == 422
