from fastapi import APIRouter, Query

from app.database.models.trade_plan import TradePlan
from app.database.sqlserver import SessionLocal
from app.utils.freshness import freshness_status
from app.utils.signal_validation import validate_trade_plan_direction


router = APIRouter(prefix="/trade-plan", tags=["Trade Plan"])


def serialize_trade_plan(trade, stale_after_seconds):
    validation = validate_trade_plan_direction(
        trade.side,
        trade.entry_price,
        trade.target1,
    )

    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "target1": trade.target1,
        "target2": trade.target2,
        "target3": trade.target3,
        "risk_reward": trade.risk_reward,
        "confidence": trade.confidence,
        "status": trade.status,
        "exit_price": trade.exit_price,
        "result": trade.result,
        "pnl_percent": trade.pnl_percent,
        "closed_at": trade.closed_at,
        "created_at": trade.created_at,
        "freshness": freshness_status(trade.created_at, stale_after_seconds),
        "is_valid_trade_plan": validation["is_valid"],
        "validation_errors": validation["errors"],
    }


@router.get("/{symbol}")
def get_trade_plan(
    symbol: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):

    db = SessionLocal()

    try:

        query = db.query(TradePlan).filter(TradePlan.symbol == symbol)

        if status:

            query = query.filter(TradePlan.status == status.upper())

        trades = (
            query.order_by(TradePlan.created_at.desc())
            .limit(limit)
            .all()
        )

        records = [
            serialize_trade_plan(trade, stale_after_seconds)
            for trade in trades
        ]

        return {
            "symbol": symbol,
            "source": "trade_plans",
            "status_filter": status.upper() if status else None,
            "count": len(records),
            "latest": records[0] if records else None,
            "records": records,
        }

    finally:

        db.close()
