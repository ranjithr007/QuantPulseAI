from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from app.backtesting.matched_exit_replay import compare_records, replay_trade
from scripts.check_matched_exit_replay import build_output_payload

START = datetime(2026, 9, 1)


def trade(**changes):
    data = dict(id=1, symbol="TEST", side="LONG", strategy_id="TEST", strategy_version="v1",
        opened_at=START, entry_price=100., initial_stop_loss=97., target1=106., target2=109.,
        target1_fraction=.75, position_notional_inr=10000., max_hold_hours=1,
        exit_policy="PAPER_ATR_STRUCTURE_V1", fee_bps=7.5)
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
