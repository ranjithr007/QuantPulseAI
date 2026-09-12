"""Gated V2G outcome review for frozen V2F entry-strategy cohorts."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import text

from app.backtesting.entry_strategy_holdout_readiness import (
    assess_entry_holdout_readiness,
    collect_candidate_entries,
    load_manifest,
)
from app.backtesting.matched_entry_quality import (
    CURRENT_EXIT_CONTROL_SPECS,
    build_entry_quality_report,
)
from app.backtesting.matched_exit_replay import compare_records
from app.database.models.funding_rates import FundingRate
from app.database.models.market_candles import MarketCandle
from app.database.models.strategy_shadow_trade import StrategyShadowTrade


OUTCOME_VERSION = "entry_strategy_holdout_outcomes_v2g"
ENTRY_FIELDS = (
    "id", "symbol", "side", "strategy_id", "strategy_version", "opened_at",
    "entry_price", "initial_stop_loss", "target1", "target2",
    "target1_fraction", "position_notional_inr", "max_hold_hours",
    "exit_policy", "fee_bps", "planned_entry_price",
    "entry_slippage_percent", "confidence", "entry_timeframe", "regime",
    "risk_reward", "execution_evidence_json", "trailing_activation_r",
)
MAX_PATH_ROWS_PER_SYMBOL = 50_000


def build_entry_holdout_outcome_report(session, *, observed_at=None, manifest_path=None):
    """Return LOCKED without accessing outcome sources until every cohort is ready."""

    manifest, digest = load_manifest(manifest_path)
    _make_transaction_read_only(session)
    entries = collect_candidate_entries(session, manifest)
    readiness = assess_entry_holdout_readiness(
        entries,
        manifest,
        observed_at=observed_at,
        manifest_sha256=digest,
    )
    if not readiness["outcome_review_unlocked"]:
        session.rollback()
        return {
            "contract": OUTCOME_VERSION,
            "status": "LOCKED_PENDING_PROSPECTIVE_SAMPLE",
            "readiness": readiness,
            "outcome_sources_accessed": False,
            "promotion_allowed": False,
            "next_action": readiness["governance"]["next_action"],
        }

    minimum = int(manifest["minimum_mature_trades_per_candidate"])
    mature_cutoff = _naive(readiness["mature_entry_cutoff_inclusive"])
    cutoff = _naive(manifest["holdout_start_exclusive"])
    selected_ids = []
    for candidate in manifest["candidates"]:
        cohort = sorted(
            (
                row for row in entries
                if row["strategy_id"] == candidate["strategy_id"]
                and row["strategy_version"] == candidate["strategy_version"]
                and cutoff < _naive(row["opened_at"]) <= mature_cutoff
            ),
            key=lambda row: (_naive(row["opened_at"]), row["trade_id"]),
        )
        selected_ids.extend(row["trade_id"] for row in cohort[:minimum])

    source = (
        session.query(*(getattr(StrategyShadowTrade, field) for field in ENTRY_FIELDS))
        .filter(StrategyShadowTrade.id.in_(selected_ids))
        .order_by(StrategyShadowTrade.opened_at, StrategyShadowTrade.id)
        .all()
    )
    records = [SimpleNamespace(**dict(zip(ENTRY_FIELDS, row))) for row in source]
    if len(records) != minimum * len(manifest["candidates"]):
        session.rollback()
        raise ValueError("Frozen entry holdout sample changed between readiness and outcome load")
    if any(
        record.max_hold_hours != int(manifest["maturation_hours"])
        for record in records
    ):
        session.rollback()
        raise ValueError("Frozen entry holdout contains a non-contract holding horizon")

    candles, funding = _load_paths(session, records)
    session.rollback()
    replay = compare_records(
        records,
        candles,
        funding,
        exit_slippage_bps=10.0,
        slippage_scenarios=(0.0, 5.0, 10.0, 15.0),
        policy_specs=CURRENT_EXIT_CONTROL_SPECS,
        engine="entry_strategy_holdout_current_exit_control_v2g",
    )
    diagnostics = build_entry_quality_report(replay, records)
    evaluations = _evaluate_frozen_cohorts(diagnostics, manifest)
    complete = all(item["paired_trades"] == minimum for item in evaluations)
    return {
        "contract": OUTCOME_VERSION,
        "status": "RESEARCH_REVIEW_READY" if complete else "INVALID_REPLAY_COVERAGE",
        "readiness": readiness,
        "outcome_sources_accessed": True,
        "selection": "First mature post-cutoff trades per frozen strategy/version",
        "pre_registered_metrics_only": True,
        "evaluations": evaluations,
        "research_ranking": [
            item["strategy_version_cohort"]
            for item in sorted(
                evaluations,
                key=lambda item: (
                    item["decision"] == "RESEARCH_PASS",
                    item.get("average_return_after_funding_percent") or float("-inf"),
                ),
                reverse=True,
            )
        ],
        "promotion_allowed": False,
        "governance": {
            "automatic_strategy_update": False,
            "paper_policy_changed": False,
            "live_policy_changed": False,
            "human_review_required": True,
            "note": (
                "A research pass is evidence for review only. A new immutable "
                "strategy version requires a separate authorized change."
            ),
        },
    }


def _load_paths(session, records):
    candles, funding = {}, {}
    for symbol in sorted({record.symbol for record in records}):
        selected = [record for record in records if record.symbol == symbol]
        start = min(record.opened_at for record in selected) - timedelta(minutes=5)
        end = max(
            record.opened_at + timedelta(hours=record.max_hold_hours)
            for record in selected
        )
        candle_fields = (
            "symbol", "open_time", "close_time", "open_price", "high_price",
            "low_price", "close_price",
        )
        candle_rows = (
            session.query(*(getattr(MarketCandle, field) for field in candle_fields))
            .filter(
                MarketCandle.symbol == symbol,
                MarketCandle.timeframe == "5m",
                MarketCandle.venue == "BINANCE",
                MarketCandle.market_type == "FUTURES",
                MarketCandle.is_final.is_(True),
                MarketCandle.quality_state.in_(("VERIFIED", "RECONCILED")),
                MarketCandle.open_time >= start,
                MarketCandle.close_time <= end,
            )
            .order_by(MarketCandle.open_time)
            .limit(MAX_PATH_ROWS_PER_SYMBOL + 1)
            .all()
        )
        if len(candle_rows) > MAX_PATH_ROWS_PER_SYMBOL:
            raise ValueError(f"Frozen {symbol} candle path exceeds the bounded V2G query")
        candles[symbol] = [
            SimpleNamespace(**dict(zip(candle_fields, row))) for row in candle_rows
        ]
        funding_rows = (
            session.query(FundingRate.funding_time, FundingRate.rate)
            .filter(
                FundingRate.symbol == symbol,
                FundingRate.funding_time > start,
                FundingRate.funding_time <= end,
            )
            .order_by(FundingRate.funding_time)
            .limit(10_001)
            .all()
        )
        if len(funding_rows) > 10_000:
            raise ValueError(f"Frozen {symbol} funding path exceeds the bounded V2G query")
        funding[symbol] = [
            SimpleNamespace(funding_time=row.funding_time, rate=row.rate)
            for row in funding_rows
        ]
    return candles, funding


def _evaluate_frozen_cohorts(report, manifest):
    metrics = {
        item["cohort"]: item
        for item in (report.get("entry_cohorts") or {}).get(
            "strategy_version_cohort", []
        )
    }
    gates = manifest["outcome_gates"]
    minimum = int(manifest["minimum_mature_trades_per_candidate"])
    evaluations = []
    for candidate in manifest["candidates"]:
        name = f'{candidate["strategy_id"]}|{candidate["strategy_version"]}'
        values = metrics.get(name, {})
        failures = []
        paired = int(values.get("trades") or 0)
        funding_complete = int(values.get("funding_complete_trades") or 0)
        win_rate = values.get("win_rate_after_funding_percent")
        average = values.get("average_return_after_funding_percent")
        profit_factor = values.get("profit_factor_after_funding")
        target1 = int(values.get("target1_hits") or 0)
        losses = int(values.get("pre_t1_losing_stops") or 0)
        if paired != minimum:
            failures.append(f"paired replay coverage is {paired}/{minimum}")
        if gates["require_complete_funding_coverage"] and funding_complete != paired:
            failures.append(f"complete funding coverage is {funding_complete}/{paired}")
        if win_rate is None or win_rate < float(gates["minimum_win_rate_percent"]):
            failures.append("win rate is below the frozen threshold")
        if average is None or average <= float(
            gates["minimum_average_return_after_funding_percent_exclusive"]
        ):
            failures.append("average cost-adjusted return is not positive")
        infinite_profit_factor = (
            profit_factor is None
            and win_rate == 100
            and average is not None
            and average > 0
        )
        if not infinite_profit_factor and (
            profit_factor is None
            or profit_factor < float(gates["minimum_profit_factor_after_funding"])
        ):
            failures.append("profit factor is below the frozen threshold")
        if (
            gates["require_target1_hits_greater_than_pre_t1_losing_stops"]
            and target1 <= losses
        ):
            failures.append("Target 1 hits do not exceed pre-T1 losing stops")
        evaluations.append(
            {
                "label": candidate["label"],
                "strategy_id": candidate["strategy_id"],
                "strategy_version": candidate["strategy_version"],
                "strategy_version_cohort": name,
                "decision": "RESEARCH_PASS" if not failures else "RESEARCH_FAIL",
                "failures": failures,
                "paired_trades": paired,
                "funding_complete_trades": funding_complete,
                "win_rate_after_funding_percent": win_rate,
                "average_return_after_funding_percent": average,
                "profit_factor_after_funding": profit_factor,
                "profit_factor_interpretation": (
                    "INFINITE_NO_LOSING_TRADES"
                    if infinite_profit_factor
                    else "FINITE" if profit_factor is not None else "UNAVAILABLE"
                ),
                "target1_hits": target1,
                "pre_t1_losing_stops": losses,
                "adverse_first_0_25r_percent_of_resolved": values.get(
                    "adverse_first_0_25r_percent_of_resolved"
                ),
            }
        )
    return evaluations


def _make_transaction_read_only(session):
    bind = getattr(session, "bind", None)
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '20s'"))
        session.execute(text("SET LOCAL lock_timeout = '1s'"))


def _naive(value):
    from app.backtesting.entry_strategy_holdout_readiness import _utc

    return _utc(value).replace(tzinfo=None)
