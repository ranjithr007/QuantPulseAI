import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models.strategy_learning import StrategyLearningEvaluation
from app.database.models.strategy_learning import StrategyVersionConfig
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.app_notification import AppNotification
from app.database.sqlserver import Base
from app.strategies.learning import analyze_strategy_trades
from app.strategies.learning import apply_learning_parameters
from app.strategies.learning import candidate_rearm_blocker
from app.strategies.learning import evaluate_due_strategy_versions
from app.strategies.learning import latest_evaluations
from app.strategies.learning import strategy_definitions
from app.strategies.registry import CORE_SIGNAL_STRATEGY


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _trade(index, *, winning):
    opened = datetime(2026, 1, 1) + timedelta(hours=index)
    return SimpleNamespace(
        id=index,
        status="CLOSED",
        symbol="DOGEUSDT",
        side="LONG",
        exit_policy="PAPER_STAGED_EXIT_V2",
        initial_stop_loss=99.25,
        stop_loss=99.25,
        execution_evidence_json=json.dumps({
            "entry_quality_profile": "CORE_SIGNAL_V1",
            "exit_management_profile": "IMMEDIATE_TRAIL_V1",
            "sizing_policy": "TEST_SIZING_V1",
            "release_version": "TEST_RELEASE_V1",
        }),
        exit_evidence_json=json.dumps({
            "version": "PAPER_EXIT_EVIDENCE_V1",
            "classification": "TARGET2" if winning else "INITIAL_STOP",
            "evidence_kind": "LIVE_MARK",
            "observed_at": (opened + timedelta(hours=1)).isoformat(),
            "quote_age_seconds": 0.5,
        }),
        entry_timeframe="2h",
        regime="RANGE_ACCUMULATION",
        realized_pnl_inr=1000.0 if winning else -500.0,
        fees_percent=0.15,
        funding_cost_percent=0.0,
        target1_hit_at=opened + timedelta(minutes=30) if winning else None,
        exit_reason="TARGET2" if winning else "STOP",
        opened_at=opened,
        closed_at=opened + timedelta(hours=1),
        created_at=opened,
    )


def _row(index, *, winning, strategy_version=None):
    item = _trade(index, winning=winning)
    return StrategyShadowTrade(
        trade_plan_id=index,
        risk_decision_id=index,
        symbol=item.symbol,
        side=item.side,
        strategy_id=CORE_SIGNAL_STRATEGY["id"],
        strategy_version=strategy_version or CORE_SIGNAL_STRATEGY["version"],
        strategy_decision_snapshot_id=index,
        entry_price=100.0,
        stop_loss=99.25,
        initial_stop_loss=99.25,
        exit_policy=item.exit_policy,
        execution_evidence_json=item.execution_evidence_json,
        exit_evidence_json=item.exit_evidence_json,
        target1=101.5,
        target2=102.3,
        entry_timeframe=item.entry_timeframe,
        regime=item.regime,
        target1_hit_at=item.target1_hit_at,
        exit_reason=item.exit_reason,
        result="WIN" if winning else "LOSS",
        pnl_percent=1.0 if winning else -0.5,
        realized_pnl_inr=item.realized_pnl_inr,
        fees_percent=item.fees_percent,
        funding_cost_percent=0.0,
        status="CLOSED",
        opened_at=item.opened_at,
        closed_at=item.closed_at,
        created_at=item.created_at,
    )


def test_analysis_requires_target_successes_to_exceed_initial_stops():
    report = analyze_strategy_trades(
        [_trade(index, winning=index < 10) for index in range(30)]
    )

    assert report["metrics"]["target_successes"] == 10
    assert report["metrics"]["initial_stop_failures"] == 20
    assert report["gates"]["targets_exceed_initial_stops"] is False
    assert report["promotion_candidate"] is False


def test_analysis_marks_profitable_30_trade_window_as_candidate_only():
    report = analyze_strategy_trades(
        [_trade(index, winning=index < 18) for index in range(30)]
    )

    assert report["metrics"]["win_rate"] == 60.0
    assert report["metrics"]["profit_factor"] == 3.0
    assert report["promotion_candidate"] is True
    assert report["authorizes_live_execution"] is False


def test_analysis_blocks_promotion_when_any_exit_trigger_evidence_is_missing():
    trades = [_trade(index, winning=index < 18) for index in range(30)]
    trades[-1].exit_evidence_json = None

    report = analyze_strategy_trades(trades)

    assert report["metrics"]["verified_exit_evidence_trades"] == 29
    assert report["metrics"]["missing_exit_evidence_trades"] == 1
    assert report["gates"]["timely_recorded_exit_evidence_complete"] is False
    assert report["promotion_candidate"] is False


def test_analysis_excludes_recorded_but_stale_exit_trigger():
    trades = [_trade(index, winning=index < 18) for index in range(30)]
    evidence = json.loads(trades[-1].exit_evidence_json)
    evidence["quote_age_seconds"] = 6.0
    trades[-1].exit_evidence_json = json.dumps(evidence)

    report = analyze_strategy_trades(trades)

    assert report["metrics"]["closed_trades"] == 29
    assert report["metrics"]["verified_exit_evidence_trades"] == 29
    assert report["metrics"]["timely_exit_evidence_trades"] == 29
    assert report["metrics"]["stale_or_untimed_exit_evidence_trades"] == 0
    assert report["metrics"]["excluded_operationally_contaminated_trades"] == 1
    assert report["promotion_candidate"] is False


def test_due_evaluation_creates_one_immutable_paper_candidate():
    db = _session()
    try:
        db.add_all([_row(index + 1, winning=index < 10) for index in range(30)])
        db.commit()

        first = evaluate_due_strategy_versions(db)
        second = evaluate_due_strategy_versions(db)

        assert first["evaluated_count"] == 1
        assert first["created_candidate_count"] == 1
        assert second["evaluated_count"] == 0
        assert db.query(StrategyLearningEvaluation).count() == 1
        config = db.query(StrategyVersionConfig).one()
        assert config.status == "COLLECTING"
        assert config.live_execution_enabled is False
        assert config.version != CORE_SIGNAL_STRATEGY["version"]
        definitions = strategy_definitions(db, CORE_SIGNAL_STRATEGY["id"])
        assert len(definitions) == 2
        assert definitions[1]["strategy_type"] == "AUTO_CANDIDATE"
        notifications = db.query(AppNotification).all()
        assert len(notifications) == 1
        assert notifications[0].event_type == "STRATEGY_CANDIDATE_CREATED"
        assert notifications[0].category == "STRATEGY"
        assert notifications[0].severity == "WARNING"
        metadata = json.loads(notifications[0].metadata_json)
        assert metadata["liveExecutionEnabled"] is False
        assert metadata["candidateVersion"] == config.version
        assert metadata["windowSize"] == 30
    finally:
        db.close()


def test_due_evaluation_waits_for_thirty_closed_trades():
    db = _session()
    try:
        db.add_all([_row(index + 1, winning=True) for index in range(29)])
        db.commit()

        result = evaluate_due_strategy_versions(db)

        assert result["evaluated_count"] == 0
        assert result["created_candidate_count"] == 0
        assert db.query(StrategyLearningEvaluation).count() == 0
        assert db.query(StrategyVersionConfig).count() == 0
        assert db.query(AppNotification).count() == 0
    finally:
        db.close()


def test_stale_learning_snapshot_is_recalculated_but_cannot_promote():
    db = _session()
    try:
        rows = [_row(index + 1, winning=True) for index in range(30)]
        contaminated = rows[-1]
        contaminated.exit_reason = "TIME_EXIT"
        contaminated.max_hold_hours = 48
        contaminated.closed_at = contaminated.opened_at + timedelta(hours=60)
        db.add_all(rows)
        db.add(
            StrategyLearningEvaluation(
                strategy_id=CORE_SIGNAL_STRATEGY["id"],
                strategy_version=CORE_SIGNAL_STRATEGY["version"],
                milestone=30,
                window_size=30,
                closed_trade_count=30,
                status="PROMOTION_CANDIDATE",
                metrics_json=json.dumps({"metric_version": "STOP_CAUSE_COHORT_V3"}),
                diagnostics_json="{}",
                recommended_changes_json="{}",
            )
        )
        db.commit()

        payload = latest_evaluations(db, [CORE_SIGNAL_STRATEGY])[
            (CORE_SIGNAL_STRATEGY["id"], CORE_SIGNAL_STRATEGY["version"])
        ]

        assert payload["status"] == "CLEAN_EVIDENCE_RECALCULATED_PREVIEW"
        assert payload["metrics"]["total_observed_closed_trades"] == 30
        assert payload["metrics"]["excluded_operationally_contaminated_trades"] == 1
        assert payload["metrics"]["evidence_snapshot_persisted"] is False
        assert payload["metrics"]["gates"]["persisted_clean_evidence_snapshot"] is False
        assert payload["candidate_version"] is None
        assert payload["authorizes_live_execution"] is False
    finally:
        db.close()


def test_latest_evaluations_returns_latest_row_for_each_requested_strategy():
    db = _session()
    second_definition = {
        **CORE_SIGNAL_STRATEGY,
        "id": "SECOND_TEST_STRATEGY",
        "version": "second_test_v1",
    }
    current_metrics = json.dumps({
        "metric_version": "STOP_CAUSE_COHORT_V3",
        "evidence_policy": "CLEAN_OPERATIONAL_EXIT_EVIDENCE_V2",
        "evidence_snapshot_persisted": True,
    })
    try:
        db.add_all([
            StrategyLearningEvaluation(
                strategy_id=CORE_SIGNAL_STRATEGY["id"],
                strategy_version=CORE_SIGNAL_STRATEGY["version"],
                milestone=30,
                window_size=30,
                closed_trade_count=30,
                status="COLLECTING",
                metrics_json=current_metrics,
                diagnostics_json="{}",
                recommended_changes_json="{}",
            ),
            StrategyLearningEvaluation(
                strategy_id=CORE_SIGNAL_STRATEGY["id"],
                strategy_version=CORE_SIGNAL_STRATEGY["version"],
                milestone=40,
                window_size=30,
                closed_trade_count=40,
                status="LATEST_CORE",
                metrics_json=current_metrics,
                diagnostics_json="{}",
                recommended_changes_json="{}",
            ),
            StrategyLearningEvaluation(
                strategy_id=second_definition["id"],
                strategy_version=second_definition["version"],
                milestone=30,
                window_size=30,
                closed_trade_count=30,
                status="LATEST_SECOND",
                metrics_json=current_metrics,
                diagnostics_json="{}",
                recommended_changes_json="{}",
            ),
        ])
        db.commit()

        payloads = latest_evaluations(db, [CORE_SIGNAL_STRATEGY, second_definition])

        assert payloads[(CORE_SIGNAL_STRATEGY["id"], CORE_SIGNAL_STRATEGY["version"])]["status"] == "LATEST_CORE"
        assert payloads[(second_definition["id"], second_definition["version"])]["status"] == "LATEST_SECOND"
    finally:
        db.close()


def test_latest_evaluations_batches_stale_strategy_trade_recalculation():
    db = _session()
    second_definition = {
        **CORE_SIGNAL_STRATEGY,
        "id": "SECOND_TEST_STRATEGY",
        "version": "second_test_v1",
    }
    try:
        first_trade = _row(1, winning=True)
        second_trade = _row(2, winning=False)
        second_trade.strategy_id = second_definition["id"]
        second_trade.strategy_version = second_definition["version"]
        db.add_all([
            first_trade,
            second_trade,
            StrategyLearningEvaluation(
                strategy_id=CORE_SIGNAL_STRATEGY["id"],
                strategy_version=CORE_SIGNAL_STRATEGY["version"],
                milestone=30,
                window_size=30,
                closed_trade_count=30,
                status="COLLECTING",
                metrics_json="{}",
                diagnostics_json="{}",
                recommended_changes_json="{}",
            ),
            StrategyLearningEvaluation(
                strategy_id=second_definition["id"],
                strategy_version=second_definition["version"],
                milestone=30,
                window_size=30,
                closed_trade_count=30,
                status="COLLECTING",
                metrics_json="{}",
                diagnostics_json="{}",
                recommended_changes_json="{}",
            ),
        ])
        db.commit()
        statements = []

        def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", record_statement)
        try:
            payloads = latest_evaluations(db, [CORE_SIGNAL_STRATEGY, second_definition])
        finally:
            event.remove(engine, "before_cursor_execute", record_statement)

        trade_selects = [
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("SELECT")
            and "FROM strategy_shadow_trades" in statement
        ]
        assert len(trade_selects) == 1
        assert len(payloads) == 2
        assert all(
            payload["status"] == "CLEAN_EVIDENCE_RECALCULATED_PREVIEW"
            for payload in payloads.values()
        )
    finally:
        db.close()


def test_profitable_base_review_notifies_once_without_creating_candidate():
    db = _session()
    try:
        db.add_all([_row(index + 1, winning=index < 18) for index in range(30)])
        db.commit()

        evaluate_due_strategy_versions(db)
        evaluate_due_strategy_versions(db)

        notification = db.query(AppNotification).one()
        assert notification.event_type == "STRATEGY_LEARNING_PASSED"
        assert notification.severity == "SUCCESS"
        assert db.query(StrategyVersionConfig).count() == 0
    finally:
        db.close()


def test_failed_candidate_notifies_replacement_without_enabling_live():
    db = _session()
    try:
        db.add_all([_row(index + 1, winning=False) for index in range(30)])
        db.commit()
        first = evaluate_due_strategy_versions(db)
        version = first["candidates"][0]["version"]
        db.add_all([
            _row(index + 101, winning=False, strategy_version=version)
            for index in range(30)
        ])
        db.commit()

        result = evaluate_due_strategy_versions(db)
        evaluate_due_strategy_versions(db)

        assert result["created_candidate_count"] == 1
        notifications = db.query(AppNotification).order_by(AppNotification.id).all()
        assert [row.event_type for row in notifications] == [
            "STRATEGY_CANDIDATE_CREATED", "STRATEGY_CANDIDATE_REPLACED"
        ]
        metadata = json.loads(notifications[-1].metadata_json)
        assert metadata["candidateVersion"] != version
        assert metadata["liveExecutionEnabled"] is False
        assert all(not row.live_execution_enabled for row in db.query(StrategyVersionConfig))
    finally:
        db.close()


def test_profitable_candidate_becomes_paper_champion_but_never_live():
    db = _session()
    try:
        db.add_all([_row(index + 1, winning=index < 10) for index in range(30)])
        db.commit()
        first = evaluate_due_strategy_versions(db)
        candidate_version = first["candidates"][0]["version"]

        db.add_all(
            [
                _row(index + 101, winning=index < 18, strategy_version=candidate_version)
                for index in range(30)
            ]
        )
        db.commit()

        result = evaluate_due_strategy_versions(db)
        config = (
            db.query(StrategyVersionConfig)
            .filter(StrategyVersionConfig.version == candidate_version)
            .one()
        )

        assert result["evaluated_count"] == 1
        assert result["created_candidate_count"] == 0
        assert config.status == "PAPER_CHAMPION"
        assert config.official_paper_enabled is True
        assert config.live_execution_enabled is False
        assert result["live_execution_enabled"] is False
        notifications = db.query(AppNotification).order_by(AppNotification.id).all()
        assert [row.event_type for row in notifications] == [
            "STRATEGY_CANDIDATE_CREATED",
            "STRATEGY_PAPER_CHAMPION",
        ]
        assert notifications[-1].severity == "SUCCESS"
    finally:
        db.close()


def test_candidate_filters_quarantined_symbol_without_rewriting_evidence():
    definition = {
        **CORE_SIGNAL_STRATEGY,
        "version": "core_signal_candidate_test",
        "source_evaluation_id": 1,
        "learning_parameters": {
            "minimum_confidence": 40,
            "blocked_symbols": ["DOGEUSDT"],
            "require_fresh_inputs": True,
        },
    }
    payload = {
        "symbol": "DOGEUSDT",
        "confirmation": {"confidence": 65},
        "trigger": {"status": "READY", "side": "LONG", "entry_timeframe": "1h"},
        "trade_plan": {"entry_timeframe": "1h"},
        "trade_plan_validation": {"is_valid": True, "errors": []},
        "timeframes": [
            {"timeframe": "1h", "status": "OK", "freshness": {"is_stale": False}}
        ],
    }

    candidate = apply_learning_parameters(payload, definition)

    assert payload["trigger"]["status"] == "READY"
    assert candidate["trigger"]["status"] == "WAIT"
    assert "quarantined" in candidate["trigger"]["reason"]


def test_candidate_filters_never_rewrite_entry_stop_or_targets():
    definition = {
        **CORE_SIGNAL_STRATEGY,
        "version": "core_signal_candidate_geometry_test",
        "source_evaluation_id": 1,
        "learning_parameters": {
            "minimum_confidence": 40,
            "allowed_timeframes": ["1h"],
            "allowed_regimes": ["BULL_PULLBACK"],
            "require_fresh_inputs": True,
        },
    }
    trade_plan = {
        "entry_timeframe": "1h",
        "regime": "BULL_PULLBACK",
        "entry_price": 100.0,
        "stop_loss": 99.25,
        "target1": 101.5,
        "target2": 102.3,
    }
    payload = {
        "symbol": "BTCUSDT",
        "confirmation": {"confidence": 65},
        "trigger": {"status": "READY", "side": "LONG", "entry_timeframe": "1h"},
        "trade_plan": trade_plan,
        "trade_plan_validation": {"is_valid": True, "errors": []},
        "timeframes": [
            {
                "timeframe": "1h",
                "status": "OK",
                "regime": "BULL_PULLBACK",
                "confidence": 65,
                "freshness": {"is_stale": False},
            }
        ],
    }

    candidate = apply_learning_parameters(payload, definition)

    assert candidate["trade_plan"] == trade_plan
    assert payload["trade_plan"] == trade_plan
    assert candidate["trigger"]["status"] == "READY"


def test_candidate_rearm_requires_new_candle_but_not_for_opposite_side():
    db = _session()
    candle_time = datetime(2026, 1, 1, 12)
    try:
        for snapshot_id, source_time in ((1, candle_time), (2, candle_time)):
            db.add(
                DecisionSnapshot(
                    id=snapshot_id,
                    symbol="BTCUSDT",
                    timeframe="1h",
                    source_timestamp=source_time,
                    effective_timestamp=source_time + timedelta(seconds=snapshot_id),
                    feature_version="test",
                    decision_version=f"test_{snapshot_id}",
                    strategy_id="CORE_SIGNAL",
                    strategy_version="candidate",
                    quality_state="OK",
                    decision="ELIGIBLE",
                    snapshot_json="{}",
                )
            )
        db.commit()
        previous = SimpleNamespace(
            id=1,
            symbol="BTCUSDT",
            side="LONG",
            status="CLOSED",
            exit_reason="STOP",
            strategy_decision_snapshot_id=1,
            closed_at=candle_time + timedelta(minutes=30),
            created_at=candle_time,
        )
        definition = {"learning_parameters": {"require_signal_rearm": True}}
        candidate = {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "trade_plan": {"strategy_decision_snapshot_id": 2},
        }

        assert "newly closed" in candidate_rearm_blocker(
            db, definition, [previous], candidate
        )
        candidate["side"] = "SHORT"
        assert candidate_rearm_blocker(db, definition, [previous], candidate) is None
    finally:
        db.close()
