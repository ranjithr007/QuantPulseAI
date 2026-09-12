"""Print a read-only matched-entry exit study from the configured database."""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_output_payload(report, *, summary_only=False):
    """Return a presentation copy without mutating the replay report."""
    payload = dict(report)
    trades = payload.get("trades") or []
    payload["trade_details_count"] = len(trades)
    payload["trade_details_included"] = not summary_only
    if summary_only:
        payload.pop("trades", None)
    return payload


def parse_as_of(value):
    if value is None:
        return datetime.utcnow()
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def select_records(source, *, per_strategy, as_of, mature_only):
    """Select newest records per immutable strategy version after maturity eligibility."""
    counts, records = {}, []
    immature = maturity_unknown = 0
    for record in source:
        hold = getattr(record, "max_hold_hours", None)
        opened = getattr(record, "opened_at", None)
        if mature_only:
            if opened is None or not isinstance(hold, (float, int)) or hold <= 0:
                maturity_unknown += 1
                continue
            if opened + timedelta(hours=float(hold)) > as_of:
                immature += 1
                continue
        key = (record.strategy_id, record.strategy_version)
        if counts.get(key, 0) >= per_strategy:
            continue
        counts[key] = counts.get(key, 0) + 1
        records.append(record)
    return records, {
        "source_trades": len(source),
        "immature_trades": immature,
        "maturity_unknown_trades": maturity_unknown,
        "maturity_eligible_trades": len(source) - immature - maturity_unknown,
        "mature_only": mature_only,
        "selected_before_path_quality": len(records),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", choices=("strategy", "consolidated"), default="strategy")
    parser.add_argument("--days", type=int, choices=range(1, 31), default=7)
    parser.add_argument("--per-strategy", type=int, choices=range(1, 101), default=30)
    parser.add_argument("--symbol")
    parser.add_argument("--trade-id", type=int)
    parser.add_argument(
        "--study",
        choices=("exit-quality", "protection-v2d", "entry-quality-v2e"),
        default="exit-quality",
        help=(
            "Run the V2C attribution report or the V2D matched cost-safe "
            "protection candidate comparison, or diagnose V2E entry quality "
            "under one frozen current-exit control."
        ),
    )
    parser.add_argument("--as-of", help="Frozen UTC ISO timestamp; defaults to current UTC time.")
    parser.add_argument(
        "--mature-only",
        action="store_true",
        help="Select only entries whose recorded maximum holding horizon elapsed by --as-of.",
    )
    parser.add_argument("--exit-slippage-bps", type=float, default=10.0)
    parser.add_argument(
        "--slippage-scenarios",
        type=float,
        nargs="+",
        default=(0.0, 5.0, 10.0, 15.0),
        help="Research-only exit-slippage scenarios in basis points.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-trade rows while retaining coverage, exclusions, assumptions, and policy summaries.",
    )
    args = parser.parse_args()
    # Import after parsing: --help works without DB initialization or credentials.
    from sqlalchemy import text
    from app.database.sqlserver import SessionLocal
    from app.database.models.paper_trade import PaperTrade
    from app.database.models.strategy_shadow_trade import StrategyShadowTrade
    from app.database.models.market_candles import MarketCandle
    from app.database.models.funding_rates import FundingRate
    from app.backtesting.matched_exit_replay import (
        PROTECTION_CANDIDATE_SPECS,
        compare_records,
    )
    from app.backtesting.matched_entry_quality import (
        CURRENT_EXIT_CONTROL_SPECS,
        build_entry_quality_report,
    )

    model = StrategyShadowTrade if args.book == "strategy" else PaperTrade
    end = parse_as_of(args.as_of)
    start = end - timedelta(days=args.days)
    fields = ("id", "symbol", "side", "strategy_id", "strategy_version", "opened_at",
              "entry_price", "initial_stop_loss", "target1", "target2", "target1_fraction",
              "position_notional_inr", "max_hold_hours", "exit_policy", "fee_bps",
              "planned_entry_price", "entry_slippage_percent", "confidence",
              "entry_timeframe", "regime", "risk_reward", "execution_evidence_json",
              "trailing_activation_r")
    with SessionLocal() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
        query = db.query(*(getattr(model, f) for f in fields)).filter(
            model.opened_at >= start, model.opened_at <= end)
        if args.symbol:
            query = query.filter(model.symbol == args.symbol.upper())
        if args.trade_id is not None:
            query = query.filter(model.id == args.trade_id)
        source = query.order_by(model.opened_at.desc(), model.id.desc()).limit(10001).all()
        if len(source) > 10000:
            raise ValueError("More than 10,000 entries: narrow --days or --symbol. No silent truncation.")
        source_records = [SimpleNamespace(**dict(zip(fields, row))) for row in source]
        records, cohort = select_records(
            source_records,
            per_strategy=args.per_strategy,
            as_of=end,
            mature_only=args.mature_only,
        )
        candles = {}
        funding_events = {}
        for symbol in sorted({r.symbol for r in records}):
            earliest = min(r.opened_at for r in records if r.symbol == symbol) - timedelta(minutes=5)
            columns = ("symbol", "open_time", "close_time", "open_price", "high_price", "low_price", "close_price")
            rows = db.query(*(getattr(MarketCandle, f) for f in columns)).filter(
                MarketCandle.symbol == symbol, MarketCandle.timeframe == "5m",
                MarketCandle.venue == "BINANCE", MarketCandle.market_type == "FUTURES",
                MarketCandle.is_final.is_(True), MarketCandle.quality_state.in_(("VERIFIED", "RECONCILED")),
                MarketCandle.open_time >= earliest, MarketCandle.close_time <= end
            ).order_by(MarketCandle.open_time).limit(10001).all()
            if len(rows) > 10000:
                raise ValueError("Candle bound exceeded; narrow the requested period.")
            candles[symbol] = [SimpleNamespace(**dict(zip(columns, row))) for row in rows]
            funding_rows = db.query(FundingRate.funding_time, FundingRate.rate).filter(
                FundingRate.symbol == symbol,
                FundingRate.funding_time > earliest,
                FundingRate.funding_time <= end,
            ).order_by(FundingRate.funding_time).limit(10001).all()
            if len(funding_rows) > 10000:
                raise ValueError("Funding-event bound exceeded; narrow the requested period.")
            funding_events[symbol] = [
                SimpleNamespace(funding_time=row.funding_time, rate=row.rate)
                for row in funding_rows
            ]
        db.rollback()  # Release the read transaction before doing replay CPU work.
    report = compare_records(
        records,
        candles,
        funding_events,
        exit_slippage_bps=args.exit_slippage_bps,
        slippage_scenarios=args.slippage_scenarios,
        policy_specs=(PROTECTION_CANDIDATE_SPECS if args.study == "protection-v2d"
                      else CURRENT_EXIT_CONTROL_SPECS if args.study == "entry-quality-v2e"
                      else None),
        engine=(
            "matched_protection_candidates_v2d"
            if args.study == "protection-v2d"
            else "matched_entry_quality_exit_control_v1"
            if args.study == "entry-quality-v2e"
            else "matched_exit_sensitivity_v2c"
        ),
    )
    if args.study == "entry-quality-v2e":
        report = build_entry_quality_report(report, records)
    cohort.update(
        as_of_utc=end.isoformat(),
        window_start_utc=start.isoformat(),
        paired_after_path_quality=report["paired_trades"],
    )
    report.update(book=args.book, study=args.study, as_of_utc=end.isoformat(),
                  selection="Latest maturity-eligible entries per strategy/version, before path-quality exclusions" if args.mature_only else "Latest entries per strategy/version, before path-quality exclusions; immature entries may be excluded",
                  venue="BINANCE", requested_per_strategy=args.per_strategy,
                  cohort=cohort)
    print(json.dumps(build_output_payload(report, summary_only=args.summary_only), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
