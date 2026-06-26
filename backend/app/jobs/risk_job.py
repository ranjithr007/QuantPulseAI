from app.database.sqlserver import SessionLocal
from app.database.models.market_candles import MarketCandle
from app.database.models.market_features import MarketFeature
from app.repositories.candle_repository import get_latest_candle as latest_market_candle
from app.repositories.fusion_repository import FusionSignalRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.repositories._db_utils import safe_rollback

from app.risk.risk_engine import RiskEngine

from app.repositories.risk_repository import RiskRepository
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


DEFAULT_TIMEFRAME = "5m"
DEFAULT_ATR_PERCENT = 0.01


def normalize_fusion_decision(decision):
    decision = (decision or "").upper()

    if decision in {"STRONG_LONG", "LONG", "BUY"}:
        return "LONG"

    if decision in {"STRONG_SHORT", "SHORT", "SELL"}:
        return "SHORT"

    return "WAIT"


def get_latest_candle(db, symbol, timeframe):
    return latest_market_candle(db, symbol, timeframe)


def get_latest_feature(db, symbol, timeframe):
    return (
        db.query(MarketFeature)
        .filter(MarketFeature.Symbol == symbol, MarketFeature.Timeframe == timeframe)
        .order_by(MarketFeature.CreatedAt.desc())
        .first()
    )


def resolve_risk_inputs(db, signal):
    timeframe = getattr(signal, "timeframe", None) or DEFAULT_TIMEFRAME
    candle = get_latest_candle(db, signal.symbol, timeframe)

    if candle is None or candle.close_price is None:
        return None

    price = float(candle.close_price)
    feature = get_latest_feature(db, signal.symbol, timeframe)
    atr = getattr(feature, "ATR", None)

    if atr is None or atr <= 0:
        atr = price * DEFAULT_ATR_PERCENT

    return {
        "timeframe": timeframe,
        "signal": normalize_fusion_decision(signal.decision),
        "price": price,
        "atr": float(atr),
        "confidence": float(signal.confidence or 0),
    }


def approve_open_trade_plans(db, risk_repo, engine):
    trade_repo = TradePlanRepository()
    summary = {
        "processed": 0,
        "approved": 0,
        "rejected": 0,
        "errors": [],
    }

    for trade in trade_repo.get_open_trades(db):
        summary["processed"] += 1
        try:
            result = engine.analyze_trade_plan(
                symbol=trade.symbol,
                side=trade.side,
                entry=trade.entry_price,
                stop_loss=trade.stop_loss,
                target1=trade.target1,
                target2=trade.target2,
                confidence=float(trade.confidence or 0),
                risk_percent=1,
            )
            result["thesis_id"] = getattr(trade, "thesis_id", None)

            risk_repo.save(result)

            if result["decision"] == "APPROVE":
                summary["approved"] += 1
            else:
                summary["rejected"] += 1
                summary["errors"].append(
                    f"{trade.symbol} {trade.side}: {result.get('reason')}"
                )
        except Exception as ex:
            summary["rejected"] += 1
            summary["errors"].append(
                f"{trade.symbol} {trade.side}: {summarize_network_error(ex)}"
            )

    return summary


def run_risk_job():
    db = SessionLocal()
    try:
        summary = {
            "processed": 0,
            "saved": 0,
            "rejected": 0,
            "skipped": 0,
            "errors": [],
            "trade_plans": {
                "processed": 0,
                "approved": 0,
                "rejected": 0,
                "errors": [],
            },
        }
        fusion_repo = FusionSignalRepository()
        risk_repo = RiskRepository()
        engine = RiskEngine()
        signals = fusion_repo.get_latest_signals(db)

        for s in signals:
            summary["processed"] += 1
            try:
                inputs = resolve_risk_inputs(db, s)

                if inputs is None:
                    summary["skipped"] += 1
                    summary["errors"].append(
                        f"No latest market candle for {s.symbol} {getattr(s, 'timeframe', None) or DEFAULT_TIMEFRAME}"
                    )
                    continue

                result = engine.analyze(
                    symbol=s.symbol,
                    signal=inputs["signal"],
                    price=inputs["price"],
                    atr=inputs["atr"],
                    confidence=inputs["confidence"],
                )
                result["thesis_id"] = getattr(s, "thesis_id", None)

                risk_repo.save(result)

                if result["decision"] == "TAKE_TRADE":
                    summary["saved"] += 1
                else:
                    summary["rejected"] += 1
            except Exception as ex:
                summary["rejected"] += 1
                summary["errors"].append(
                    f"{s.symbol} {getattr(s, 'timeframe', None) or DEFAULT_TIMEFRAME}: {summarize_network_error(ex)}"
                )

        summary["trade_plans"] = approve_open_trade_plans(db, risk_repo, engine)

        print("Risk Engine Completed", summary)
        return summary

    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Risk job error:", summarize_network_error(ex))
        summary["errors"].append(summarize_network_error(ex))
        return summary

    finally:
        db.close()
