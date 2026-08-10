"""Rebuild the latest downstream intelligence snapshots from final candles.

This is deliberately generation-scoped and paper-only.  It does not delete
legacy rows or create paper trades.  Historical replay remains responsible for
recomputing every event; this command refreshes the live/dashboard source rows
after the R1 canonical candle rebuild.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime
from app.database.models.point_in_time_snapshots import FeatureSnapshot
from app.database.sqlserver import SessionLocal, USING_SQLITE_FALLBACK
from app.features.point_in_time_feature_service import build_feature_snapshot
from app.features.point_in_time_feature_service import persist_feature_snapshot
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.orderflow.delta_engine import analyze_orderflow
from app.regimes.regime_engine import analyze_market
from app.repositories.candle_repository import get_latest_candles
from app.repositories.feature_repository import save_market_feature
from app.repositories.feature_repository import get_latest_feature
from app.repositories.orderflow_repository import OrderFlowRepository
from app.repositories.smc_repository import SMCRepository
from app.services.fusion_service import FusionService
from app.engines.smc_engine import SMCEngine


DEFAULT_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "DOGEUSDT",
)


def _utc_now():
    return datetime.now(timezone.utc)


def rebuild_latest_snapshots(symbols=None, timeframes=None, *, dry_run=False):
    symbols = tuple(symbols or DEFAULT_SYMBOLS)
    timeframes = tuple(timeframes or OFFICIAL_ENTRY_TIMEFRAMES)
    generation_id = "r1-clean-" + _utc_now().strftime("%Y%m%dT%H%M%SZ")
    report = {
        "source": "r1_downstream_snapshot_rebuild",
        "generation_id": generation_id,
        "status": "DRY_RUN" if dry_run else "RUNNING",
        "execution_scope": "PAPER_ONLY",
        "symbols": list(symbols),
        "timeframes": list(timeframes),
        "scopes": [],
    }

    if USING_SQLITE_FALLBACK and not dry_run:
        raise RuntimeError("Downstream rebuild requires SQL Server; SQLite fallback is not evidence-grade")

    db = SessionLocal()
    fusion = FusionService()
    smc_engine = SMCEngine()
    try:
        for symbol in symbols:
            for timeframe in timeframes:
                scope = {"symbol": symbol, "timeframe": timeframe, "status": "PASS"}
                candles = get_latest_candles(db, symbol, timeframe, limit=200)
                scope["candle_count"] = len(candles)
                if len(candles) < 20:
                    scope.update({"status": "BLOCKED", "reason": "INSUFFICIENT_FINAL_CANDLES"})
                    report["scopes"].append(scope)
                    continue

                latest = candles[-1]
                source_timestamp = getattr(latest, "open_time", None) or getattr(latest, "candle_time", None)
                effective_timestamp = getattr(latest, "close_time", None)
                scope["source_timestamp"] = str(source_timestamp)
                scope["effective_timestamp"] = str(effective_timestamp)
                scope["is_final"] = bool(getattr(latest, "is_final", False))
                scope["quality_state"] = getattr(latest, "quality_state", None)

                if not scope["is_final"] or effective_timestamp is None:
                    scope.update({"status": "BLOCKED", "reason": "LATEST_CANDLE_NOT_FINAL"})
                    report["scopes"].append(scope)
                    continue

                if dry_run:
                    report["scopes"].append(scope)
                    continue

                feature_record = get_latest_feature(db, symbol, timeframe)
                existing_pit = (
                    db.query(FeatureSnapshot)
                    .filter(
                        FeatureSnapshot.symbol == symbol,
                        FeatureSnapshot.timeframe == timeframe,
                        FeatureSnapshot.source_timestamp == source_timestamp,
                        FeatureSnapshot.effective_timestamp == effective_timestamp,
                        FeatureSnapshot.feature_version == "feature_factory_v1",
                    )
                    .first()
                )
                if existing_pit is None:
                    feature_snapshot = build_feature_snapshot(
                        symbol,
                        timeframe,
                        candles,
                        source_timestamp=source_timestamp,
                        effective_timestamp=effective_timestamp,
                    )
                    save_market_feature(db, feature_snapshot["feature"])
                    persist_feature_snapshot(db, feature_snapshot)
                    feature_record = get_latest_feature(db, symbol, timeframe)
                else:
                    scope["feature_snapshot"] = "ALREADY_PRESENT"
                    scope["feature"] = "ALREADY_PRESENT"
                    scope["regime"] = "ALREADY_PRESENT"
                    scope["orderflow"] = "ALREADY_PRESENT"
                    scope["smc"] = "ALREADY_PRESENT"
                    scope["fusion"] = "ALREADY_PRESENT"
                    report["scopes"].append(scope)
                    continue

                previous = (
                    db.query(MarketRegime)
                    .filter(MarketRegime.Symbol == symbol, MarketRegime.Timeframe == timeframe)
                    .order_by(MarketRegime.Id.desc())
                    .first()
                )
                regime_result = analyze_market(feature_record, previous)
                db.add(
                    MarketRegime(
                        Symbol=regime_result["symbol"],
                        Timeframe=regime_result["timeframe"],
                        Regime=regime_result["regime"],
                        Confidence=regime_result["confidence"],
                        RecommendedStrategy=regime_result["strategy"],
                        Reason=regime_result["reason"],
                    )
                )
                db.commit()

                previous_cvd = OrderFlowRepository.get_last_cvd(db, symbol)
                flow_result = analyze_orderflow(candles, previous_cvd, True)
                OrderFlowRepository.save_orderflow(db, symbol, timeframe, flow_result)

                smc_result = smc_engine.analyze(candles)
                smc_result["symbol"] = symbol
                smc_result["timeframe"] = timeframe
                SMCRepository().save(db, smc_result)

                fusion_result = fusion.generate(db, symbol, timeframe)
                scope.update(
                    {
                        "feature": "REBUILT",
                        "regime": "REBUILT",
                        "orderflow": "REBUILT",
                        "smc": "REBUILT",
                        "fusion": "REBUILT",
                        "fusion_decision": fusion_result.get("decision"),
                    }
                )
                report["scopes"].append(scope)

        failed = [scope for scope in report["scopes"] if scope["status"] != "PASS"]
        report["status"] = "FAIL" if failed else ("DRY_RUN" if dry_run else "PASS")
        report["completed_at"] = _utc_now().isoformat()
        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframes", default=",".join(OFFICIAL_ENTRY_TIMEFRAMES))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = rebuild_latest_snapshots(
        [item.strip().upper() for item in args.symbols.split(",") if item.strip()],
        [item.strip() for item in args.timeframes.split(",") if item.strip()],
        dry_run=args.dry_run,
    )
    rendered = json.dumps(report, indent=2, default=str)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["status"] in {"PASS", "DRY_RUN"} else 1)


if __name__ == "__main__":
    main()
