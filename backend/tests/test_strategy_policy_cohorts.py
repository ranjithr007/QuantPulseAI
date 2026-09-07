import json

from test_strategy_learning import _trade, _session, _row
from app.strategies.learning import analyze_strategy_trades, evaluate_due_strategy_versions, resolve_strategy_definition
from app.strategies.registry import MARKET_MOVE_ENTRY_STRATEGY
from app.database.models.strategy_learning import StrategyVersionConfig


def test_learning_never_mixes_old_fixed_and_new_adaptive_exits():
    rows = [_trade(index, winning=index < 20) for index in range(30)]
    adaptive = _trade(31, winning=True)
    adaptive.exit_policy = "PAPER_ATR_STRUCTURE_V1"
    report = analyze_strategy_trades(rows + [adaptive])
    assert report["metrics"]["closed_trades"] == 1
    assert report["metrics"]["cohort_closed_trades"] == 1
    assert len(report["diagnostics"]["by_policy_cohort"]) == 2
    assert report["promotion_candidate"] is False


def test_missing_policy_metadata_is_diagnostic_not_promotion_evidence():
    rows = [_trade(index, winning=True) for index in range(30)]
    for item in rows:
        item.execution_evidence_json = None
    report = analyze_strategy_trades(rows)
    assert report["metrics"]["win_rate"] == 100
    assert report["metrics"]["unknown_cohort_trades"] == 30
    assert report["metrics"]["analysis_scope"] == "LEGACY_DIAGNOSTIC_ONLY"
    assert report["promotion_candidate"] is False
    assert report["authorizes_live_execution"] is False


def test_sizing_release_and_entry_profile_each_create_separate_cohorts():
    rows = [_trade(index, winning=True) for index in range(4)]
    for item, field in zip(rows[1:], ("sizing_policy", "release_version", "entry_quality_profile")):
        evidence = json.loads(item.execution_evidence_json)
        evidence[field] = "NEW_VERSION"
        item.execution_evidence_json = json.dumps(evidence)
    report = analyze_strategy_trades(rows)
    assert len(report["diagnostics"]["by_policy_cohort"]) == 4
    assert report["metrics"]["closed_trades"] == 1


def test_losing_trailed_stop_is_not_reported_as_untouched_initial_stop():
    initial = _trade(1, winning=False)
    trailed = _trade(2, winning=False)
    trailed.stop_loss = 99.8
    unknown = _trade(3, winning=False)
    unknown.initial_stop_loss = None
    protected = _trade(4, winning=True)
    protected.exit_reason = "STOP"
    report = analyze_strategy_trades([initial, trailed, unknown, protected])
    metrics = report["metrics"]
    assert metrics["pre_t1_losing_stops"] == 3
    assert metrics["initial_stop_failures"] == 1
    assert metrics["trailed_stop_pre_t1_exits"] == 1
    assert metrics["unknown_stop_exits"] == 1
    assert metrics["protected_stop_after_t1_exits"] == 1


def test_frozen_experiment_does_not_spawn_mutable_auto_candidates():
    db = _session()
    try:
        rows = [_row(index + 1, winning=False) for index in range(30)]
        for row in rows:
            row.strategy_id = MARKET_MOVE_ENTRY_STRATEGY["id"]
            row.strategy_version = MARKET_MOVE_ENTRY_STRATEGY["version"]
        db.add_all(rows)
        db.commit()
        result = evaluate_due_strategy_versions(db)
        assert result["evaluated_count"] == 1
        assert result["created_candidate_count"] == 0
        assert db.query(StrategyVersionConfig).count() == 0
    finally:
        db.close()


def test_database_flag_cannot_promote_frozen_experiment_to_consolidated():
    db = _session()
    try:
        db.add(StrategyVersionConfig(
            strategy_id=MARKET_MOVE_ENTRY_STRATEGY["id"], version="unexpected_override",
            base_version=MARKET_MOVE_ENTRY_STRATEGY["version"], decision_version="test_override",
            status="PAPER_CHAMPION", parameters_json="{}", official_paper_enabled=True,
            live_execution_enabled=True,
        ))
        db.commit()
        definition = resolve_strategy_definition(db, MARKET_MOVE_ENTRY_STRATEGY["id"], "unexpected_override")
        assert definition["official_execution_enabled"] is False
        assert definition["live_execution_enabled"] is False
    finally:
        db.close()
