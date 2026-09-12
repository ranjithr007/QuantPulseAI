import json
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from app.backtesting.matched_entry_quality import (
    CURRENT_EXIT_CONTROL_SPECS,
    build_entry_quality_report,
)
from app.backtesting.matched_exit_replay import (
    PROTECTION_CANDIDATE_SPECS,
    compare_records,
    replay_trade,
)
from scripts.check_matched_exit_replay import build_output_payload, parse_as_of, select_records

START = datetime(2026, 9, 1)


def trade(**changes):
    data = dict(id=1, symbol="TEST", side="LONG", strategy_id="TEST", strategy_version="v1",
        opened_at=START, entry_price=100., initial_stop_loss=97., target1=106., target2=109.,
        target1_fraction=.75, position_notional_inr=10000., max_hold_hours=1,
        exit_policy="PAPER_ATR_STRUCTURE_V1", fee_bps=7.5, confidence=52.,
        entry_timeframe="1h", regime="RANGE", risk_reward=2.,
        execution_evidence_json=None)
    return NS(**{**data, **changes})


def bars(prices=None):
    prices = prices or [100.] * 12
    return [NS(symbol="TEST", open_time=START+timedelta(minutes=5*i),
        close_time=START+timedelta(minutes=5*(i+1)), open_price=p,
        high_price=p, low_price=p, close_price=p) for i, p in enumerate(prices)]


def test_three_variants_frozen_entry_and_profit_giveback():
    record = trade()
    result = replay_trade(record, bars([102., 102.5, 101., 99.] + [99.] * 8))
    assert result["PROFIT_PROTECTION"]["pnl_before_funding_inr"] > 0
    assert result["IMMEDIATE"]["pnl_before_funding_inr"] < 0
    assert result["DELAYED_1R"]["events"][-1]["reason"] == "TIME_EXIT"
    assert record.initial_stop_loss == 97 and record.entry_price == 100


def test_short_is_symmetric_and_costs_are_charged():
    result = replay_trade(trade(side="SHORT", initial_stop_loss=103, target1=94, target2=91),
                          bars([98., 97.5, 99., 101.] + [101.] * 8))
    assert result["PROFIT_PROTECTION"]["pnl_before_funding_inr"] > 0
    assert result["IMMEDIATE"]["pnl_before_funding_inr"] < 0
    flat = replay_trade(trade(), bars())
    assert flat["IMMEDIATE"]["return_before_funding_percent"] < -.24


@pytest.mark.parametrize("variant", ["missing", "gap", "duplicate", "invalid"])
def test_bad_paths_excluded_from_every_alternative(variant):
    path = bars()
    if variant == "missing":
        path = path[:-1]
    elif variant == "gap":
        del path[4]
    elif variant == "duplicate":
        path.insert(4, path[4])
    else:
        path[3].high_price = float("nan")
    result = compare_records([trade()], {"TEST": path})
    assert result["paired_trades"] == 0
    assert sum(result["exclusions"].values()) == 1
    assert result["promotion_allowed"] is False


def test_entry_overlap_does_not_use_pre_entry_wick():
    path = bars()
    path.append(NS(**{**vars(path[-1]), "open_time": START+timedelta(hours=1),
                     "close_time": START+timedelta(hours=1, minutes=5)}))
    path[0].low_price = 90
    out = replay_trade(trade(opened_at=START+timedelta(minutes=2)), path)
    assert out["IMMEDIATE"]["events"][-1]["reason"] == "TIME_EXIT"
    assert out["IMMEDIATE"]["ambiguous_bars"] == 2


def test_both_targets_close_exactly_once():
    path = bars()
    path[0].high_price = 110
    out = replay_trade(trade(), path)["IMMEDIATE"]
    assert [e["reason"] for e in out["events"]] == ["TARGET1", "TARGET2"]
    assert [e["fraction"] for e in out["events"]] == [.75, .25]


def test_stop_first_and_gap_fill():
    path = bars()
    path[0].high_price, path[0].low_price, path[0].open_price = 110, 95, 96
    out = replay_trade(trade(), path)["IMMEDIATE"]
    assert out["events"][0]["reason"] == "STOP_BEFORE_T1"
    assert out["events"][0]["fill"] < 96
    assert out["ambiguous_bars"] == 1


def test_stop_update_effective_next_bar_and_never_loosened():
    path = bars([102., 101.8, 101.] + [101.] * 9)
    path[0].low_price = 99  # Not hit by newly computed 101 stop retroactively.
    out = replay_trade(trade(), path)["PROFIT_PROTECTION"]
    assert out["events"][0]["at"] == path[2].close_time.isoformat()
    assert out["final_stop"] == 101


def test_missing_recorded_policy_not_replaced():
    with pytest.raises(ValueError, match="unsupported_recorded_policy"):
        replay_trade(trade(exit_policy=None), bars())
    with pytest.raises(ValueError, match="missing_recorded_geometry"):
        replay_trade(trade(initial_stop_loss=None), bars())


def test_deterministic_report_and_before_funding_label():
    a = compare_records([trade()], {"TEST": bars()})
    assert a == compare_records([trade()], {"TEST": bars()})
    assert a["status"] == "APPROXIMATE_BEFORE_FUNDING"
    assert len(a["summary"]) == 3
    assert a["summary"][0]["paired_trades"] == 1


def test_summary_output_keeps_audit_fields_and_omits_only_trade_rows():
    report = compare_records([trade()], {"TEST": bars()})
    compact = build_output_payload(report, summary_only=True)

    assert "trades" not in compact
    assert compact["trade_details_count"] == 1
    assert compact["trade_details_included"] is False
    assert compact["paired_trades"] == report["paired_trades"]
    assert compact["exclusions"] == report["exclusions"]
    assert compact["assumptions"] == report["assumptions"]
    assert compact["summary"] == report["summary"]
    assert len(report["trades"]) == 1  # Presentation must not mutate the canonical report.


def test_full_output_retains_trade_rows_and_labels_them():
    report = compare_records([trade()], {"TEST": bars()})
    full = build_output_payload(report)

    assert full["trades"] == report["trades"]
    assert full["trade_details_count"] == 1
    assert full["trade_details_included"] is True


def test_cost_decomposition_reconciles_and_gross_does_not_change_with_slippage():
    record = trade(planned_entry_price=99.9)
    zero = replay_trade(record, bars(), exit_slippage_bps=0)["IMMEDIATE"]
    costly = replay_trade(record, bars(), exit_slippage_bps=15)["IMMEDIATE"]
    zero_costs = zero["cost_decomposition"]
    costly_costs = costly["cost_decomposition"]

    assert zero_costs["post_fill_gross_return_percent"] == costly_costs["post_fill_gross_return_percent"]
    assert zero_costs["signal_gross_return_percent"] == costly_costs["signal_gross_return_percent"]
    assert costly_costs["entry_slippage_cost_percent"] == pytest.approx(.1)
    assert zero_costs["exit_slippage_cost_percent"] == 0
    assert costly_costs["exit_slippage_cost_percent"] == pytest.approx(.15)
    assert costly["return_before_funding_percent"] < zero["return_before_funding_percent"]
    assert abs(costly_costs["post_fill_reconciliation_error_percent"]) < 1e-8
    assert abs(costly_costs["signal_reconciliation_error_percent"]) < 1e-8


def test_stored_funding_is_path_specific_and_missing_event_is_not_zero():
    path = bars([106.] * 120)
    record = trade(max_hold_hours=10, planned_entry_price=100.)
    event = NS(funding_time=START + timedelta(hours=8), rate=.0001)
    funded = replay_trade(record, path, funding_events=[event])["IMMEDIATE"]
    missing = replay_trade(record, path, funding_events=[])["IMMEDIATE"]

    assert funded["cost_decomposition"]["funding_coverage_status"] == "COMPLETE"
    assert funded["cost_decomposition"]["funding_events_expected"] == 1
    assert funded["cost_decomposition"]["funding_cost_percent"] == pytest.approx(.0025)
    assert funded["return_after_funding_percent"] == pytest.approx(
        funded["return_before_funding_percent"] - .0025
    )
    assert missing["cost_decomposition"]["funding_coverage_status"] == "INCOMPLETE"
    assert missing["cost_decomposition"]["funding_cost_percent"] is None
    assert missing["return_after_funding_percent"] is None


def test_slippage_sensitivity_reprices_net_without_rewriting_gross():
    report = compare_records(
        [trade(planned_entry_price=100.)],
        {"TEST": bars()},
        slippage_scenarios=(0, 10, 15),
    )
    immediate = [row for row in report["slippage_sensitivity"] if row["policy"] == "IMMEDIATE"]

    assert len(immediate) == 3
    assert len({round(row["average_post_fill_gross_return_percent"], 8) for row in immediate}) == 1
    assert immediate[0]["average_net_return_before_funding_percent"] > immediate[-1]["average_net_return_before_funding_percent"]
    assert report["overall_summary"][0]["paired_trades"] == 1


def test_report_distinguishes_complete_and_incomplete_funding_coverage():
    record = trade(max_hold_hours=10, planned_entry_price=100.)
    path = bars([100.] * 120)
    event = NS(funding_time=START + timedelta(hours=8), rate=.0001)
    complete = compare_records([record], {"TEST": path}, {"TEST": [event]})
    incomplete = compare_records([record], {"TEST": path}, {"TEST": []})

    assert complete["status"] == "RESEARCH_ONLY_AFTER_STORED_FUNDING"
    assert complete["cost_coverage"]["funding_complete_policy_paths"] == 3
    assert incomplete["status"] == "RESEARCH_ONLY_PARTIAL_FUNDING_COVERAGE"
    assert incomplete["cost_coverage"]["funding_complete_policy_paths"] == 0
    assert incomplete["overall_summary"][0]["average_return_after_funding_percent"] is None


def test_mature_selection_is_timestamp_based_and_reproducible():
    as_of = START + timedelta(hours=48)
    mature = trade(id=1, opened_at=START - timedelta(hours=1), max_hold_hours=48)
    immature = trade(id=2, opened_at=START + timedelta(hours=1), max_hold_hours=48)
    selected, cohort = select_records(
        [immature, mature], per_strategy=30, as_of=as_of, mature_only=True
    )

    assert [row.id for row in selected] == [1]
    assert cohort["source_trades"] == 2
    assert cohort["immature_trades"] == 1
    assert cohort["selected_before_path_quality"] == 1
    assert parse_as_of("2026-09-01T05:30:00+05:30") == START


def test_v2b_exit_taxonomy_separates_initial_and_protected_stops():
    initial_path = bars()
    initial_path[0].low_price = 96
    initial_path[2].high_price = 106
    initial = replay_trade(trade(), initial_path)["IMMEDIATE"]

    protected_path = bars([102., 101., 101.] + [101.] * 9)
    protected = replay_trade(trade(), protected_path)["PROFIT_PROTECTION"]

    assert initial["exit_taxonomy"] == "INITIAL_OR_ADVERSE_STOP"
    assert initial["economic_result"] == "LOSS"
    assert initial["recovered_t1_after_pre_t1_stop"] is True
    assert initial["full_horizon_excursions"]["mfe_r"] == 2
    assert protected["exit_taxonomy"] == "PRE_T1_PROTECTED_PROFIT_STOP"


def test_v2b_reports_non_degenerate_exit_quality_geometry():
    stopped_path = bars()
    stopped_path[0].low_price = 96
    stopped_path[2].high_price = 106
    report = compare_records([trade(planned_entry_price=100.)], {"TEST": stopped_path})
    quality = report["overall_summary"][0]["exit_quality"]

    assert report["engine"] == "matched_exit_sensitivity_v2c"
    assert quality["exit_taxonomy_counts"] == {"INITIAL_OR_ADVERSE_STOP": 1}
    assert quality["economic_result_counts"] == {"LOSS": 1}
    assert quality["loser_mfe_r_p50"] == 0
    assert quality["pre_t1_stop_recovery_rate_percent"] == 100


def test_v2c_attributes_the_terminal_stop_source_and_result():
    initial_path = bars()
    initial_path[0].low_price = 96
    initial = replay_trade(trade(), initial_path)["IMMEDIATE"]

    trailing = replay_trade(
        trade(), bars([102., 98.5] + [98.5] * 10)
    )["IMMEDIATE"]
    cost_safe = replay_trade(
        trade(), bars([102., 101.] + [101.] * 10)
    )["PROFIT_PROTECTION"]
    post_t1 = replay_trade(
        trade(), bars([106., 103.] + [103.] * 10)
    )["IMMEDIATE"]

    assert initial["terminal_stop_source"] == "INITIAL_HARD_STOP"
    assert trailing["terminal_stop_source"] == "ONE_FOR_ONE_TRAILING"
    assert cost_safe["terminal_stop_source"] == "COST_SAFE_PROFIT_PROTECTION"
    assert post_t1["terminal_stop_source"] == "POST_T1_PROTECTION"

    report = compare_records(
        [trade(planned_entry_price=100.)], {"TEST": initial_path}
    )
    quality = report["overall_summary"][0]["exit_quality"]
    assert quality["terminal_stop_source_counts"] == {"INITIAL_HARD_STOP": 1}
    assert quality["terminal_stop_source_economic_results"] == {
        "INITIAL_HARD_STOP": {"LOSS": 1}
    }
    assert quality["terminal_stop_source_recovery"]["INITIAL_HARD_STOP"] == {
        "stops": 1,
        "recovered_to_t1": 0,
        "recovery_rate_percent": 0,
    }


def test_v2d_current_candidate_is_an_exact_v2c_profit_protection_control():
    path = bars([102., 101.] + [101.] * 10)
    current = replay_trade(trade(), path)["PROFIT_PROTECTION"]
    candidate = replay_trade(
        trade(), path, policy_specs=PROTECTION_CANDIDATE_SPECS
    )["CURRENT_PROFIT_PROTECTION"]

    assert candidate == current


def test_v2d_half_r_candidate_moves_directly_to_a_cost_safe_stop():
    record = trade(initial_stop_loss=99.25, target1=101.5, target2=102.3)
    path = bars([100.4, 100.3, 99.6] + [99.6] * 9)
    outcomes = replay_trade(
        record, path, policy_specs=PROTECTION_CANDIDATE_SPECS
    )
    baseline = outcomes["CURRENT_PROFIT_PROTECTION"]
    candidate = outcomes["COST_SAFE_0_5R"]

    assert baseline["terminal_stop_source"] == "ONE_FOR_ONE_TRAILING"
    assert baseline["economic_result"] == "LOSS"
    assert candidate["terminal_stop_source"] == "COST_SAFE_PROFIT_PROTECTION"
    assert candidate["economic_result"] == "WIN"


def test_v2d_comparison_is_paired_and_research_only():
    report = compare_records(
        [trade(planned_entry_price=100.)],
        {"TEST": bars()},
        policy_specs=PROTECTION_CANDIDATE_SPECS,
        engine="matched_protection_candidates_v2d",
    )

    assert report["engine"] == "matched_protection_candidates_v2d"
    assert report["promotion_allowed"] is False
    assert report["paired_trades"] == 1
    assert len(report["overall_summary"]) == len(PROTECTION_CANDIDATE_SPECS)
    assert {
        row["policy"] for row in report["overall_summary"]
    } == set(PROTECTION_CANDIDATE_SPECS)


def test_v2e_full_horizon_marks_adverse_first_and_same_bar_ambiguity():
    adverse_first_path = bars()
    adverse_first_path[0].low_price = 99
    adverse_first_path[1].high_price = 102
    adverse_first = replay_trade(
        trade(), adverse_first_path,
        policy_specs=CURRENT_EXIT_CONTROL_SPECS,
    )["RECORDED_CURRENT_EXIT"]["full_horizon_excursions"]

    ambiguous_path = bars()
    ambiguous_path[0].low_price = 99
    ambiguous_path[0].high_price = 102
    ambiguous = replay_trade(
        trade(), ambiguous_path,
        policy_specs=CURRENT_EXIT_CONTROL_SPECS,
    )["RECORDED_CURRENT_EXIT"]["full_horizon_excursions"]

    assert adverse_first["first_0_25r_excursion"] == "ADVERSE_FIRST"
    assert adverse_first["time_to_adverse_0_25r_minutes"] == 5
    assert adverse_first["time_to_0_25r_minutes"] == 10
    assert ambiguous["first_0_25r_excursion"] == "SAME_5M_BAR_AMBIGUOUS"


def test_v2e_reports_recorded_entry_cohorts_without_promoting_or_filtering():
    record = trade(
        planned_entry_price=99.95,
        execution_evidence_json=json.dumps({
            "entry_quality_profile": "CONFIRMED_PRICE_STRUCTURE_V1",
            "entry_quality_passed": True,
            "setup_type": "PULLBACK",
            "price_structure": "BULLISH",
            "entry_drift_atr": 0.2,
            "execution_mark_age_seconds": 8,
        }),
    )
    base = compare_records(
        [record], {"TEST": bars()},
        policy_specs=CURRENT_EXIT_CONTROL_SPECS,
        engine="matched_entry_quality_exit_control_v1",
    )
    report = build_entry_quality_report(base, [record])

    assert report["engine"] == "matched_entry_quality_v2e"
    assert report["promotion_allowed"] is False
    assert report["control_policy"] == "RECORDED_CURRENT_EXIT"
    assert report["entry_evidence_coverage"]["entry_quality_result"] == 1
    assert report["overall_entry_quality"]["trades"] == 1
    assert report["overall_entry_quality"]["minimum_sample_reached"] is False
    assert report["entry_cohorts"]["entry_quality_status"][0]["cohort"] == "PASS"
    assert report["trades"][0]["entry_drift_atr_band"] == "LE_0_25R"
    assert "summary" not in report


def test_v2e_control_honors_each_trades_recorded_trailing_activation():
    path = bars([100.5, 99.5] + [99.5] * 10)
    delayed_record = trade(
        trailing_activation_r=1.0,
        initial_stop_loss=99.25,
        target1=101.5,
        target2=102.3,
    )
    recorded = replay_trade(
        delayed_record, path, policy_specs=CURRENT_EXIT_CONTROL_SPECS
    )["RECORDED_CURRENT_EXIT"]
    forced_immediate = replay_trade(
        delayed_record,
        path,
        policy_specs={
            "FORCED_IMMEDIATE": {
                "trailing_activation_r": 0.0,
                "protection_activation_percent": 1.0,
                "disable_one_for_one_trailing": False,
            }
        },
    )["FORCED_IMMEDIATE"]

    assert recorded["terminal_stop_source"] is None
    assert forced_immediate["terminal_stop_source"] == "ONE_FOR_ONE_TRAILING"
