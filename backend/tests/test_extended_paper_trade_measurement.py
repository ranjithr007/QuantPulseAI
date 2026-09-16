from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.paper_trade_api import get_paper_trade_measurement
from app.api.v1.signals_api import _persist_ready_watchlist_payload
from app.database.models.paper_trade import PaperTrade
from app.paper_trading.measurement import MeasurementGates
from app.paper_trading.measurement import build_measurement_report
from app.paper_trading.validation_policy import PaperValidationPolicy
from app.paper_trading.validation_policy import build_architecture_paper_gate


AS_OF = datetime(2026, 6, 23, 12, 0, 0)


def trade(
    pnl_percent,
    *,
    symbol="BTCUSDT",
    side="LONG",
    mode="intraday",
    timeframe="5m",
    regime="TRENDING_BULL",
    confidence=80,
    opened_days_ago=60,
    fees_percent=0.08,
):
    return SimpleNamespace(
        status="CLOSED",
        pnl_percent=pnl_percent,
        symbol=symbol,
        side=side,
        mode=mode,
        entry_timeframe=timeframe,
        regime=regime,
        confidence=confidence,
        opened_at=AS_OF - timedelta(days=opened_days_ago),
        created_at=AS_OF - timedelta(days=opened_days_ago),
        fees_percent=fees_percent,
    )


def gates(**overrides):
    values = {
        "min_closed_trades": 4,
        "min_observation_days": 30,
        "min_profit_factor": 1.25,
        "min_expectancy_percent": 0,
        "min_total_return_percent": 0,
        "max_drawdown_percent": 15,
        "min_cohort_closed_trades": 2,
    }
    values.update(overrides)
    return MeasurementGates(**values)


def test_profitable_history_passes_only_with_sufficient_evidence():
    records = [trade(3), trade(-1), trade(2), trade(-1)]
    for record in records:
        record.strategy_id = "CORE_FUSION"
        record.strategy_version = "core_fusion_v1"
    report = build_measurement_report(
        records,
        gates=gates(),
        as_of=AS_OF,
    )

    assert report["status"] == "PASS"
    assert report["evaluation"]["evidence_sufficient"] is True
    assert report["overall"]["profit_factor"] == 2.5
    assert report["overall"]["expectancy_percent"] == 0.75
    assert report["overall"]["simulated_fees_percent"] == 0.32
    assert report["policy"]["win_rate_gate"] == "EVALUATED"
    assert report["policy"]["roadmap_targets"]["min_observation_days"] == 30
    assert report["policy"]["roadmap_targets"]["min_profit_factor"] == 1.25
    assert report["policy"]["roadmap_targets"]["min_reward_risk"] == 1.5
    assert report["cohorts"]["symbol"][0]["value"] == "BTCUSDT"
    assert report["cohorts"]["strategy"][0]["value"] == (
        "CORE_FUSION@core_fusion_v1"
    )
    assert report["cohorts"]["confidence_band"][0]["value"] == "80_PLUS"


def test_scenario_accuracy_uses_persisted_primary_label_and_net_result():
    winning_long = trade(1.2, side="LONG")
    winning_long.scenario_type = "BULLISH_CONTINUATION"
    losing_short = trade(-0.8, side="SHORT")
    losing_short.scenario_type = "BULLISH_CONTINUATION"

    report = build_measurement_report(
        [winning_long, losing_short],
        gates=gates(min_closed_trades=1),
        as_of=AS_OF,
    )

    assert report["scenario_accuracy"] == {
        "status": "CALCULATED",
        "evaluated_trades": 2,
        "correct": 1,
        "incorrect": 1,
        "accuracy_percent": 50.0,
        "by_scenario": [
            {
                "scenario_type": "BULLISH_CONTINUATION",
                "evaluated_trades": 2,
                "correct": 1,
                "incorrect": 1,
                "accuracy_percent": 50.0,
            }
        ],
        "note": "Accuracy uses persisted primary scenario labels and closed net PnL.",
    }


def test_regime_accuracy_compares_entry_label_with_close_observation():
    matching = trade(1.0, regime="TRENDING_BULL")
    matching.realized_regime = "TRENDING_BULL"
    changed = trade(1.0, regime="TRENDING_BULL")
    changed.realized_regime = "RANGE_NEUTRAL"

    report = build_measurement_report(
        [matching, changed],
        gates=gates(min_closed_trades=1),
        as_of=AS_OF,
    )

    assert report["regime_accuracy"]["status"] == "CALCULATED"
    assert report["regime_accuracy"]["evaluated_trades"] == 2
    assert report["regime_accuracy"]["accuracy_percent"] == 50.0
    assert report["regime_accuracy"]["confusion_pairs"] == [
        {
            "predicted_regime": "TRENDING_BULL",
            "realized_regime": "RANGE_NEUTRAL",
            "count": 1,
        },
        {
            "predicted_regime": "TRENDING_BULL",
            "realized_regime": "TRENDING_BULL",
            "count": 1,
        },
    ]


def test_good_early_results_remain_insufficient_until_sample_and_duration_gates():
    report = build_measurement_report(
        [trade(3, opened_days_ago=3), trade(2, opened_days_ago=2)],
        gates=gates(),
        as_of=AS_OF,
    )

    assert report["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["evaluation"]["performance_passed"] is True
    assert {item["name"] for item in report["evaluation"]["evidence_checks"] if not item["passed"]} == {
        "closed_trade_sample",
        "observation_period_days",
    }


def test_more_wins_than_losses_still_fails_when_loss_value_is_greater():
    trades = [trade(0.2) for _ in range(6)] + [trade(-1.0) for _ in range(4)]
    report = build_measurement_report(
        trades,
        gates=gates(min_closed_trades=10),
        as_of=AS_OF,
    )

    assert report["overall"]["win_rate"] == 60.0
    assert report["overall"]["net_pnl_percent"] == pytest.approx(-2.8)
    assert report["status"] == "FAIL"
    assert report["evaluation"]["evidence_sufficient"] is True
    assert report["evaluation"]["performance_passed"] is False


def test_confidence_calibration_does_not_promote_underperforming_higher_scores():
    records = [
        trade(1.0, confidence=55),
        trade(-0.5, confidence=58),
        trade(-1.0, confidence=70),
        trade(-1.5, confidence=80),
    ]
    report = build_measurement_report(
        records,
        gates=gates(min_cohort_closed_trades=2),
        as_of=AS_OF,
    )

    calibration = report["confidence_calibration"]
    assert calibration["status"] == "NOT_DIRECTIONALLY_ALIGNED"
    assert calibration["direction"] == "HIGHER_UNDERPERFORMS"
    assert calibration["sample_sufficient"] is True
    assert calibration["higher_confidence_promotion_eligible"] is False
    assert calibration["below_60"]["expectancy_percent"] == 0.25
    assert calibration["at_least_60"]["expectancy_percent"] == -1.25
    assert calibration["expectancy_gap_percentage_points"] == -1.5
    assert calibration["confidence_pnl_correlation"] < 0


def test_confidence_calibration_requires_both_fixed_groups_to_be_mature():
    report = build_measurement_report(
        [trade(1.0, confidence=55), trade(2.0, confidence=80)],
        gates=gates(min_cohort_closed_trades=2),
        as_of=AS_OF,
    )

    calibration = report["confidence_calibration"]
    assert calibration["status"] == "INSUFFICIENT_EVIDENCE"
    assert calibration["direction"] == "HIGHER_OUTPERFORMS"
    assert calibration["sample_sufficient"] is False
    assert calibration["higher_confidence_promotion_eligible"] is False


def test_confidence_calibration_requires_positive_higher_group_edge():
    records = [
        trade(-2.0, confidence=50),
        trade(-1.0, confidence=55),
        trade(-0.5, confidence=70),
        trade(-0.25, confidence=80),
    ]
    report = build_measurement_report(
        records,
        gates=gates(min_cohort_closed_trades=2),
        as_of=AS_OF,
    )

    calibration = report["confidence_calibration"]
    assert calibration["status"] == "DIRECTIONALLY_ALIGNED"
    assert calibration["direction"] == "HIGHER_OUTPERFORMS"
    assert calibration["sample_sufficient"] is True
    assert calibration["higher_confidence_positive_edge"] is False
    assert calibration["higher_confidence_promotion_eligible"] is False


def test_return_decomposition_reconciles_post_fill_gross_costs_and_net():
    first = trade(-1.25, fees_percent=0.15)
    first.gross_pnl_percent = -1.0
    first.funding_cost_percent = 0.10
    second = trade(0.7, fees_percent=0.15)
    second.gross_pnl_percent = 0.8
    second.funding_cost_percent = -0.05

    report = build_measurement_report(
        [first, second],
        gates=gates(min_closed_trades=1),
        as_of=AS_OF,
    )

    decomposition = report["return_decomposition"]
    assert decomposition["status"] == "COMPLETE"
    assert decomposition["reconciled_trades"] == 2
    assert decomposition["post_fill_gross_return_percent"] == -0.2
    assert decomposition["fees_percent"] == 0.3
    assert decomposition["funding_cost_percent"] == 0.05
    assert decomposition["total_cost_drag_percent"] == 0.35
    assert decomposition["net_return_percent"] == -0.55
    assert decomposition["reconciliation_error_percent"] == 0
    assert decomposition["cost_share_of_net_loss_percent"] == pytest.approx(63.64)
    assert decomposition["pre_cost_result"] == "NEGATIVE"
    assert decomposition["costs_changed_result_sign"] is False


def test_cohorts_expose_missing_legacy_context_without_inventing_it():
    legacy = trade(1)
    legacy.mode = None
    legacy.entry_timeframe = None
    legacy.regime = None
    legacy.fees_percent = None

    report = build_measurement_report(
        [legacy],
        gates=gates(min_closed_trades=1),
        as_of=AS_OF,
    )

    assert report["cohorts"]["mode"][0]["value"] == "UNKNOWN"
    assert report["data_quality"]["trades_missing_context"] == {
        "mode": 1,
        "entry_timeframe": 1,
        "regime": 1,
    }
    assert report["data_quality"]["closed_trades_missing_fee_snapshot"] == 1
    assert report["data_quality"]["closed_trades_missing_trailing_activation"] == 1


def test_measurement_flags_late_time_exit_as_operational_contamination():
    delayed = trade(-4.0, timeframe="1h")
    delayed.strategy_id = "REGIME_TREND"
    delayed.strategy_version = "regime_trend_v1"
    delayed.exit_reason = "TIME_EXIT"
    delayed.max_hold_hours = 48
    delayed.opened_at = AS_OF - timedelta(hours=60)
    delayed.closed_at = AS_OF
    delayed.exit_evidence_json = json.dumps(
        {"observations": {"coverage": "OBSERVED_ONLY"}}
    )

    report = build_measurement_report(
        [delayed],
        gates=gates(min_closed_trades=1),
        as_of=AS_OF,
    )
    quality = report["operational_exit_quality"]

    assert quality["status"] == "DEGRADED"
    assert quality["late_time_exits"] == 1
    assert quality["late_time_exit_net_pnl_percent"] == -4.0
    assert quality["maximum_exit_delay_minutes"] == 720.0
    assert quality["observed_only_exit_evidence"] == 1
    assert quality["late_time_exits_by_strategy"] == [
        {
            "strategy": "REGIME_TREND@regime_trend_v1",
            "late_time_exits": 1,
            "net_pnl_percent": -4.0,
            "max_delay_minutes": 720.0,
        }
    ]
    assert "remain included" in quality["accounting_policy"]
    assert report["overall"]["closed_trades"] == 1
    assert report["evidence_overall"]["closed_trades"] == 0
    assert report["evaluation"]["excluded_operationally_contaminated_exits"] == 1
    assert report["evaluation"]["scorecard_scope"] == "CLEAN_OPERATIONAL_EVIDENCE_ONLY"
    assert report["confidence_calibration"]["evaluated_trades"] == 0
    assert (
        report["confidence_calibration"]["excluded_operationally_contaminated_exits"]
        == 1
    )
    assert (
        report["confidence_calibration"]["evidence_scope"]
        == "CLEAN_OPERATIONAL_EVIDENCE_ONLY"
    )


def test_measurement_excludes_known_stale_recorded_trigger_from_clean_evidence():
    delayed = trade(-1.0, timeframe="1h")
    delayed.exit_reason = "STOP"
    delayed.exit_evidence_json = json.dumps(
        {
            "classification": "INITIAL_STOP",
            "evidence_kind": "CANDLE_OHLC",
            "observed_at": AS_OF.isoformat(),
            "quote_age_seconds": 76.35,
        }
    )

    report = build_measurement_report(
        [delayed],
        gates=gates(min_closed_trades=1),
        as_of=AS_OF,
    )

    quality = report["operational_exit_quality"]
    assert quality["status"] == "DEGRADED"
    assert quality["stale_recorded_exit_triggers"] == 1
    assert quality["maximum_promotion_quote_age_seconds"] == 5.0
    assert quality["maximum_recorded_trigger_quote_age_seconds"] == 76.35
    assert report["overall"]["closed_trades"] == 1
    assert report["evidence_overall"]["closed_trades"] == 0


def test_measurement_exit_classification_cohorts_prefer_recorded_evidence():
    initial = trade(-1.2)
    initial.exit_reason = "STOP"
    initial.initial_stop_loss = 95
    initial.stop_loss = 95
    initial.target1_hit_at = None
    initial.exit_evidence_json = None

    protected = trade(0.8)
    protected.exit_reason = "STOP"
    protected.initial_stop_loss = 95
    protected.stop_loss = 102
    protected.target1_hit_at = None
    protected.exit_evidence_json = json.dumps(
        {"classification": "PROTECTED_STOP_AFTER_T1"}
    )

    report = build_measurement_report(
        [initial, protected],
        gates=gates(min_closed_trades=1),
        as_of=AS_OF,
    )

    cohorts = {
        item["value"]: item for item in report["cohorts"]["exit_classification"]
    }
    assert cohorts["INITIAL_STOP"]["closed_trades"] == 1
    assert cohorts["INITIAL_STOP"]["net_pnl_percent"] == -1.2
    assert cohorts["PROTECTED_STOP_AFTER_T1"]["closed_trades"] == 1
    assert cohorts["PROTECTED_STOP_AFTER_T1"]["net_pnl_percent"] == 0.8


def test_measurement_gates_reject_invalid_configuration():
    with pytest.raises(ValueError):
        MeasurementGates(min_closed_trades=0)
    with pytest.raises(ValueError):
        MeasurementGates(max_drawdown_percent=0)


def test_measurement_gates_defaults_are_roadmap_aligned():
    gates = MeasurementGates()

    assert gates.min_observation_days == 90
    assert gates.min_profit_factor == 1.3
    assert gates.min_reward_risk == 1.5
    assert gates.min_win_rate_percent == 45.0
    assert gates.max_drawdown_percent == 20.0


def test_architecture_policy_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        PaperValidationPolicy(min_observation_days=0)
    with pytest.raises(ValueError):
        PaperValidationPolicy(min_reward_risk=0)


def test_measurement_api_exposes_configurable_gate_report():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PaperTrade.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(
            PaperTrade(
                symbol="BTCUSDT",
                side="LONG",
                status="CLOSED",
                pnl_percent=2.0,
                fees_percent=0.08,
                confidence=80,
                mode="intraday",
                entry_timeframe="1h",
                regime="TRENDING_BULL",
                opened_at=AS_OF - timedelta(days=60),
                created_at=AS_OF - timedelta(days=60),
            )
        )
        db.commit()

    with patch("app.api.v1.paper_trade_api.SessionLocal", Session):
        response = get_paper_trade_measurement(
            symbol="btcusdt",
            min_closed_trades=1,
            min_observation_days=1,
            min_profit_factor=1.25,
            min_expectancy_percent=0,
            min_total_return_percent=0,
            max_drawdown_percent=15,
            min_cohort_closed_trades=1,
        )

    assert response["source"] == "extended_paper_trade_measurement"
    assert response["symbol_filter"] == "BTCUSDT"
    assert response["report"]["overall"]["closed_trades"] == 1
    assert response["report"]["gates"]["min_closed_trades"] == 1
    assert response["architecture_gate"]["policy"]["min_observation_days"] == 90
    engine.dispose()


def test_architecture_paper_gate_passes_roadmap_thresholds():
    trades = [trade(2, opened_days_ago=90) for _ in range(80)] + [trade(-1, opened_days_ago=90) for _ in range(20)]
    report = build_measurement_report(
        trades,
        gates=gates(min_closed_trades=100, min_observation_days=90),
        as_of=AS_OF,
    )

    gate = build_architecture_paper_gate(report)

    assert gate["status"] == "PASS"
    assert gate["policy"]["min_observation_days"] == 90
    assert gate["policy"]["min_profit_factor"] == 1.3
    assert gate["policy"]["min_reward_risk"] == 1.5
    assert gate["policy"]["min_win_rate_percent"] == 45.0
    assert gate["policy"]["max_drawdown_percent"] == 20.0
    assert all(item["passed"] for item in gate["evaluation"]["checks"])


def test_architecture_paper_gate_rejects_short_history_and_weak_edge():
    trades = [trade(1, opened_days_ago=90) for _ in range(50)] + [trade(-1, opened_days_ago=90) for _ in range(50)]
    report = build_measurement_report(
        trades,
        gates=gates(min_closed_trades=100, min_observation_days=90),
        as_of=AS_OF,
    )

    gate = build_architecture_paper_gate(report)

    assert gate["status"] == "FAIL"
    assert any(not item["passed"] for item in gate["evaluation"]["checks"])
    assert gate["evaluation"]["performance_passed"] is False


def test_ready_trade_plan_snapshots_measurement_context():
    captured = {}

    class Repository:
        def has_open_trade(self, db, symbol, side):
            return False

        def save_ready_trade_plan(self, db, symbol, side, plan, confidence, context=None):
            captured.update(context or {})
            return SimpleNamespace(
                id=7,
                entry_price=plan["entry"],
                stop_loss=plan["stop_loss"],
                target1=plan["target1"],
                target2=plan["target2"],
                risk_reward=plan["risk_reward"],
                confidence=confidence,
            )

    result = _persist_ready_watchlist_payload(
        object(),
        Repository(),
        {
            "symbol": "BTCUSDT",
            "mode": "intraday",
            "timeframes_used": ["1h", "4h", "1d"],
            "trigger": {"status": "READY", "side": "LONG", "reason": "ready"},
            "trade_plan": {
                "entry": 100,
                "stop_loss": 99,
                "target1": 102,
                "target2": 103,
                "risk_reward": 2,
            },
            "trade_plan_validation": {"is_valid": True, "errors": []},
            "timeframes": [
                {
                    "timeframe": "1h",
                    "confidence": 80,
                    "component_scores": {
                        "regime": {"value": "TRENDING_BULL"},
                    },
                }
            ],
        },
    )

    assert result["action"] == "saved"
    assert captured == {
        "mode": "intraday",
        "entry_timeframe": "1h",
        "timeframe_stack": ["1h", "4h", "1d"],
        "scenario": None,
        "contradiction": None,
        "regime": "TRENDING_BULL",
        "strategy_id": "CORE_FUSION",
            "strategy_version": "core_fusion_v1",
            "strategy_decision_snapshot_id": None,
            "data_generation_id": None,
        }
