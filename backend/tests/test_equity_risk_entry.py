from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.paper_trade_api import _budget_new_paper_entry, _rebase_paper_trade_candidate
from app.paper_trading.inr_sizing import apply_equity_risk_budget, build_inr_paper_sizing


@pytest.mark.parametrize("confidence,percent", [(40, .25), (59.99, .25), (60, .5), (100, .5)])
def test_risk_budget_uses_marked_equity_not_initial_capital(confidence, percent):
    sizing = apply_equity_risk_budget(build_inr_paper_sizing(confidence), confidence, 100_000)
    assert sizing["risk_budget_inr"] == percent * 1000
    assert sizing["estimated_max_loss_inr"] <= percent * 1000
    assert sizing["position_notional_inr"] < 100_000
    assert sizing["estimated_exit_slippage_inr"] > 0
    assert sizing["estimated_funding_reserve_inr"] > 0
    assert sizing["loss_estimate_is_guaranteed"] is False


def test_wider_stops_and_higher_costs_reduce_notional_without_changing_levels():
    base = apply_equity_risk_budget(build_inr_paper_sizing(64), 64, 200_000)
    wide = apply_equity_risk_budget(build_inr_paper_sizing(64, stop_loss_percent=3), 64, 200_000)
    expensive = apply_equity_risk_budget(build_inr_paper_sizing(64), 64, 200_000,
                                        exit_slippage_percent=.5, funding_reserve_percent=.2)
    assert wide["position_notional_inr"] < base["position_notional_inr"]
    assert expensive["position_notional_inr"] < base["position_notional_inr"]
    assert wide["stop_loss_percent"] == 3


@pytest.mark.parametrize("equity", [None, 0, -1, float("nan"), float("inf")])
def test_unavailable_or_invalid_equity_cannot_produce_risk_sizing(equity):
    with pytest.raises((TypeError, ValueError)):
        apply_equity_risk_budget(build_inr_paper_sizing(60), 60, equity)


def candidate(side="LONG", strategy="MARKET_MOVE"):
    return {"symbol": "ETHUSDT", "side": side,
            "trade_plan": {"strategy_id": strategy, "strategy_version": "test_v1",
                           "entry_timeframe": "1h", "entry_price": 100,
                           "stop_loss": 98 if side == "LONG" else 102,
                           "exit_policy": "PAPER_ATR_STRUCTURE_V1", "confidence": 64},
            "risk_decision": {"id": 1, "confidence": 64, "risk_percent": 1},
            "fill_profile": {"fee_bps": 7.5}}


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_final_entry_budget_and_durable_cohort_are_from_actual_fill(side):
    original = candidate(side)
    repriced, error = _rebase_paper_trade_candidate(original, {
        "mark_price": 101, "observed_at": datetime.now(timezone.utc), "source": "TEST"})
    assert error is None
    result, error = _budget_new_paper_entry(repriced, {
        "valuation_complete": True, "equity_inr": 80_000, "remaining_margin_capacity_inr": 1000})
    assert error is None
    assert result["paper_sizing"]["margin_used_inr"] <= 1000
    assert result["paper_sizing"]["estimated_max_loss_inr"] <= 400
    assert result["execution_evidence"]["sizing_policy"] == "EQUITY_RISK_V1"
    assert result["execution_evidence"]["release_version"] == "paper_loss_protection_v1"
    assert result["execution_evidence"]["entry_fill_price"] != original["trade_plan"]["entry_price"]
    assert result["execution_risk"]["stop_loss"] == repriced["execution_risk"]["stop_loss"]
    assert "execution_evidence" not in original


@pytest.mark.parametrize("wallet", [{}, {"valuation_complete": False, "equity_inr": 200000},
                                   {"valuation_complete": True, "equity_inr": 200000,
                                    "remaining_margin_capacity_inr": 0}])
def test_final_boundary_fails_closed_without_fresh_equity_or_capacity(wallet):
    repriced, _ = _rebase_paper_trade_candidate(candidate(), {
        "mark_price": 100, "observed_at": datetime.now(timezone.utc)})
    _, error = _budget_new_paper_entry(repriced, wallet)
    assert error


def test_new_entry_candidate_is_revalidated_but_incumbent_is_unchanged():
    mark = {"mark_price": 101, "observed_at": datetime.now(timezone.utc)}
    _, error = _rebase_paper_trade_candidate(candidate(strategy="MARKET_MOVE_ENTRY"), mark)
    assert "missing" in error
    _, error = _rebase_paper_trade_candidate(candidate(), mark)
    assert error is None


def test_entry_retest_stale_or_chased_price_fails_before_budget():
    item = candidate(strategy="MARKET_MOVE_ENTRY")
    item["entry_quality"] = {
        "profile": "MARKET_MOVE_RETEST_V1", "side": "LONG", "planned_entry": 100,
        "atr": 2, "ema20": 99.5, "structure_level": 99, "tested_rejection": True,
        "spot_cvd_percent": 2, "effective_timestamp": datetime.now(timezone.utc)}
    _, error = _rebase_paper_trade_candidate(item, {
        "mark_price": 104, "observed_at": datetime.now(timezone.utc)})
    assert "0.5 ATR" in error
    item["entry_quality"]["effective_timestamp"] -= timedelta(hours=1)
    _, error = _rebase_paper_trade_candidate(item, {
        "mark_price": 100, "observed_at": datetime.now(timezone.utc)})
    assert "stale" in error


def test_entry_retest_success_preserves_structure_and_measures_fill():
    item = candidate(strategy="MARKET_MOVE_ENTRY")
    item["entry_quality"] = {
        "profile": "MARKET_MOVE_RETEST_V1", "side": "LONG", "planned_entry": 100,
        "atr": 2, "ema20": 99.5, "structure_level": 99, "tested_rejection": True,
        "spot_cvd_percent": 2, "effective_timestamp": datetime.now(timezone.utc)}
    item["execution_evidence"] = {"entry_quality_profile": "MARKET_MOVE_RETEST_V1"}
    result, error = _rebase_paper_trade_candidate(item, {
        "mark_price": 100, "observed_at": datetime.now(timezone.utc)})
    assert error is None
    assert result["execution_risk"]["stop_loss"] <= 98.5
    assert result["execution_evidence"]["entry_quality_passed"] is True
    assert result["execution_evidence"]["entry_drift_atr"] > 0  # actual simulated fill


def test_entry_budget_cannot_reuse_stale_open_position_valuation(monkeypatch):
    from app.api.v1 import paper_trade_api as api
    monkeypatch.setattr(api, "_current_paper_entry_mark", lambda symbol: {
        "mark_price": 90, "observed_at": datetime.now(timezone.utc) - timedelta(seconds=6)})
    repriced, _ = _rebase_paper_trade_candidate(candidate(), {
        "mark_price": 100, "observed_at": datetime.now(timezone.utc)})
    _, error = _budget_new_paper_entry(repriced, {
        "valuation_complete": True, "equity_inr": 200000,
        "remaining_margin_capacity_inr": 170000, "realized_pnl_inr": 0},
        open_trades=[SimpleNamespace(symbol="BTCUSDT", status="OPEN")])
    assert "5 seconds" in error


def test_entry_budget_revalues_existing_position_and_records_actual_risk(monkeypatch):
    from app.api.v1 import paper_trade_api as api
    monkeypatch.setattr(api, "_current_paper_entry_mark", lambda symbol: {
        "mark_price": 90, "observed_at": datetime.now(timezone.utc), "source": "LIVE_TEST"})
    trade = SimpleNamespace(id=1, symbol="BTCUSDT", status="OPEN", side="LONG",
                            entry_price=100, position_notional_inr=100000, margin_used_inr=20000,
                            leverage=5, remaining_position_fraction=1, fee_bps=7.5)
    repriced, _ = _rebase_paper_trade_candidate(candidate(), {
        "mark_price": 100, "observed_at": datetime.now(timezone.utc)})
    result, error = _budget_new_paper_entry(repriced, {
        "valuation_complete": True, "equity_inr": 200000,
        "remaining_margin_capacity_inr": 170000, "realized_pnl_inr": 0}, open_trades=[trade])
    assert error is None
    assert result["paper_sizing"]["equity_at_entry_inr"] == 189850
    assert result["execution_risk"]["risk_percent"] <= .5
    assert result["execution_evidence"]["equity_marks"]["BTCUSDT"]["price"] == 90


def test_entry_transaction_identity_guard_detects_hidden_commit_or_rollback():
    from app.api.v1.paper_trade_api import _entry_reservation_intact
    original = SimpleNamespace(is_active=True)
    db = SimpleNamespace(get_transaction=lambda: original)
    assert _entry_reservation_intact(db, original)
    original.is_active = False
    assert not _entry_reservation_intact(db, original)
    original.is_active = True
    db.get_transaction = lambda: SimpleNamespace(is_active=True)
    assert not _entry_reservation_intact(db, original)
