import json
from datetime import datetime, timedelta

from test_strategy_learning import _session, _row
from app.api.v1.strategy_api import _load_strategy_performance, _strategy_performance, _strategy_paper_trade_payload, _forward_test_readiness
from app.database.models.strategy_shadow_trade import StrategyShadowTrade


def test_sql_and_python_stop_classification_metrics_agree():
    db = _session()
    try:
        rows = [_row(index + 1, winning=False) for index in range(7)]
        rows[1].stop_loss = 99.8  # trailed before T1, still loses after costs
        rows[2].target1_hit_at = rows[2].opened_at + timedelta(minutes=5)
        rows[2].stop_loss = 100.75
        rows[3].side = "SHORT"
        rows[3].initial_stop_loss = 100.75
        rows[3].stop_loss = 100.25
        rows[4].initial_stop_loss = 0  # invalid raw evidence -> unknown, not initial
        rows[5].stop_loss = 98  # loosened historical stop -> unknown
        rows[6].exit_reason = "TIME_EXIT"
        db.add_all(rows)
        db.commit()
        sql = _load_strategy_performance(db, StrategyShadowTrade, [rows[0].strategy_id])[
            (rows[0].strategy_id, rows[0].strategy_version)
        ]
        direct = _strategy_performance(rows)
        for key in ("initial_stop_failures", "pre_t1_losing_stops", "trailed_stop_pre_t1_exits",
                    "protected_stop_after_t1_exits", "unknown_stop_exits"):
            assert sql[key] == direct[key], key
        assert sql["initial_stop_failures"] == 1
        assert sql["pre_t1_losing_stops"] == 5
        assert sql["trailed_stop_pre_t1_exits"] == 2
        assert sql["protected_stop_after_t1_exits"] == 1
        assert sql["unknown_stop_exits"] == 2
    finally:
        db.close()


def test_payload_preserves_recorded_evidence_and_distinguishes_inference():
    trade = _row(1, winning=False)
    trade.id = 1
    trade.stop_loss = 99.8
    trade.trailing_activation_r = 1.0
    trade.exit_evidence_json = json.dumps({"classification": "TRAILED_STOP_PRE_T1", "trigger_price": 99.79})
    payload = _strategy_paper_trade_payload(trade)
    assert payload["exit_classification"] == "TRAILED_STOP_PRE_T1"
    assert payload["exit_classification_source"] == "RECORDED_TRIGGER"
    assert payload["trailing_activation_r"] == 1.0
    assert payload["initial_stop_failure"] is False
    assert payload["pre_t1_losing_stop"] is True
    assert payload["execution_evidence"]["release_version"] == "TEST_RELEASE_V1"
    trade.exit_evidence_json = None
    assert _strategy_paper_trade_payload(trade)["exit_classification_source"] == "RECORDED_LEVELS_INFERENCE"


def test_aggregate_winners_do_not_imply_verified_cohort_ready():
    metrics = {"closed_trades": 35, "win_rate": 70, "profit_factor": 3,
               "expectancy_inr": 100, "target_successes": 25,
               "pre_t1_losing_stops": 10, "max_drawdown_percent": 2}
    result = _forward_test_readiness(metrics, require_verified_cohort=True)
    assert result["status"] == "COLLECTING_COHORT"
    assert result["promotion_candidate"] is False
    assert result["authorizes_live_execution"] is False
