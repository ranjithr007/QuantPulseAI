from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, text

from app.database.sqlserver import Base


class StrategyShadowTrade(Base):
    """Isolated Strategy Paper position owned by one immutable strategy version.

    The legacy table name is retained so existing forward-test history remains
    continuous across the user-facing Shadow -> Strategy Paper rename.
    """

    __tablename__ = "strategy_shadow_trades"

    id = Column(Integer, primary_key=True)
    trade_plan_id = Column(Integer, nullable=False, index=True)
    risk_decision_id = Column(Integer, nullable=False, index=True)
    symbol = Column(String(30), nullable=False, index=True)
    side = Column(String(20), nullable=False)
    strategy_id = Column(String(50), nullable=False, index=True)
    strategy_version = Column(String(50), nullable=False, index=True)
    strategy_decision_snapshot_id = Column(Integer, nullable=False, index=True)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    initial_stop_loss = Column(Float, nullable=False)
    target1 = Column(Float, nullable=False)
    target2 = Column(Float, nullable=False)
    position_size = Column(Float)
    position_notional_inr = Column(Float)
    margin_used_inr = Column(Float)
    leverage = Column(Float)
    risk_reward = Column(Float)
    risk_percent = Column(Float)
    confidence = Column(Float)
    entry_timeframe = Column(String(10), nullable=False)
    timeframe_stack = Column(String(40))
    regime = Column(String(50))
    exit_policy = Column(String(50))
    target1_fraction = Column(Float)
    remaining_position_fraction = Column(Float)
    max_hold_hours = Column(Integer)
    target1_hit_at = Column(DateTime)
    target1_exit_price = Column(Float)
    partial_realized_pnl_inr = Column(Float)
    exit_monitor_timeframe = Column(String(10))
    last_exit_evaluated_at = Column(DateTime)
    validation_contract_version = Column(String(100))
    fill_model_version = Column(String(100))
    planned_entry_price = Column(Float)
    entry_slippage_percent = Column(Float)
    exit_slippage_percent = Column(Float)
    funding_rate_snapshot = Column(Float)
    funding_event_count = Column(Integer)
    funding_cost_percent = Column(Float)
    fee_bps = Column(Float, default=7.5)
    fees_percent = Column(Float)
    gross_pnl_percent = Column(Float)
    realized_pnl_inr = Column(Float)
    status = Column(String(20), nullable=False, default="OPEN", index=True)
    exit_price = Column(Float)
    exit_reason = Column(String(30), index=True)
    result = Column(String(20))
    pnl_percent = Column(Float)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


Index(
    "uq_shadow_trades_one_open_strategy_symbol",
    StrategyShadowTrade.strategy_id,
    StrategyShadowTrade.strategy_version,
    StrategyShadowTrade.symbol,
    unique=True,
    postgresql_where=text("status = 'OPEN'"),
    sqlite_where=text("status = 'OPEN'"),
    mssql_where=text("status = 'OPEN'"),
)
