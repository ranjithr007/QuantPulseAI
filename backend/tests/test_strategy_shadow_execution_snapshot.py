from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.repositories.strategy_shadow_trade_repository import (
    StrategyShadowTradeRepository,
)


def _trade(
    trade_id,
    *,
    strategy_id="core_signal",
    status="CLOSED",
    closed_at=None,
    realized_pnl_inr=0.0,
    partial_realized_pnl_inr=0.0,
):
    return StrategyShadowTrade(
        id=trade_id,
        trade_plan_id=1_000 + trade_id,
        risk_decision_id=2_000 + trade_id,
        symbol=f"COIN{trade_id}USDT",
        side="LONG",
        strategy_id=strategy_id,
        strategy_version="v1",
        strategy_decision_snapshot_id=3_000 + trade_id,
        entry_price=100.0,
        stop_loss=99.0,
        initial_stop_loss=99.0,
        target1=101.0,
        target2=102.0,
        entry_timeframe="1h",
        status=status,
        closed_at=closed_at,
        realized_pnl_inr=realized_pnl_inr,
        partial_realized_pnl_inr=partial_realized_pnl_inr,
        created_at=closed_at or datetime.utcnow() - timedelta(days=10),
    )


def test_shadow_execution_snapshot_bounds_rows_but_keeps_exact_lifetime_pnl():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    StrategyShadowTrade.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    now = datetime.utcnow()

    with Session() as db:
        db.add_all(
            [
                _trade(
                    1,
                    closed_at=now - timedelta(days=10),
                    realized_pnl_inr=100.0,
                ),
                _trade(
                    2,
                    closed_at=now - timedelta(hours=2),
                    realized_pnl_inr=-25.0,
                ),
                _trade(
                    3,
                    status="OPEN",
                    partial_realized_pnl_inr=50.0,
                ),
                _trade(
                    4,
                    strategy_id="market_move",
                    closed_at=now - timedelta(hours=1),
                    realized_pnl_inr=999.0,
                ),
            ]
        )
        db.commit()

        repo = StrategyShadowTradeRepository()
        snapshot = repo.risk_snapshot_trades(
            db,
            window_start=now - timedelta(hours=24),
        )
        totals = repo.realized_pnl_by_strategy(
            db,
            {("core_signal", "v1")},
        )

    assert {trade.id for trade in snapshot} == {2, 3, 4}
    assert totals == {("core_signal", "v1"): 125.0}
    engine.dispose()
