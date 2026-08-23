"""add durable backtest market evidence

Revision ID: m1e2f3a4b5c6
Revises: l0d1e2f3a4b5
"""

from alembic import op
import sqlalchemy as sa


revision = "m1e2f3a4b5c6"
down_revision = "l0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "funding_rates" in tables:
        # Keep the latest observation for an exchange funding event before
        # enforcing its natural key. Historical P&L must charge the event once.
        op.execute(
            sa.text(
                "DELETE FROM funding_rates "
                "WHERE id NOT IN ("
                "SELECT MAX(id) FROM funding_rates "
                "GROUP BY symbol, funding_time"
                ")"
            )
        )
        inspector = sa.inspect(bind)
        indexes = {item["name"] for item in inspector.get_indexes("funding_rates")}
        if "uq_funding_rates_symbol_event" not in indexes:
            op.create_index(
                "uq_funding_rates_symbol_event",
                "funding_rates",
                ["symbol", "funding_time"],
                unique=True,
            )

    if "spot_market_candles" not in tables:
        op.create_table(
            "spot_market_candles",
            sa.Column(
                "id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                autoincrement=True,
                nullable=False,
            ),
            sa.Column("venue", sa.String(length=20), nullable=False),
            sa.Column("market_type", sa.String(length=20), nullable=False),
            sa.Column("symbol", sa.String(length=20), nullable=False),
            sa.Column("timeframe", sa.String(length=10), nullable=False),
            sa.Column("open_time", sa.DateTime(), nullable=False),
            sa.Column("close_time", sa.DateTime(), nullable=False),
            sa.Column("open_price", sa.Float(), nullable=False),
            sa.Column("high_price", sa.Float(), nullable=False),
            sa.Column("low_price", sa.Float(), nullable=False),
            sa.Column("close_price", sa.Float(), nullable=False),
            sa.Column("base_volume", sa.Float(), nullable=False),
            sa.Column("quote_volume", sa.Float(), nullable=False),
            sa.Column("trade_count", sa.Integer(), nullable=False),
            sa.Column("taker_buy_quote_volume", sa.Float(), nullable=False),
            sa.Column("taker_sell_quote_volume", sa.Float(), nullable=False),
            sa.Column("spot_delta_quote", sa.Float(), nullable=False),
            sa.Column("is_final", sa.Boolean(), nullable=False),
            sa.Column("source", sa.String(length=40), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "venue",
                "symbol",
                "timeframe",
                "open_time",
                name="uq_spot_market_candle_identity",
            ),
        )
        op.create_index(
            "ix_spot_market_candles_symbol",
            "spot_market_candles",
            ["symbol"],
        )
        op.create_index(
            "ix_spot_market_candles_lookup",
            "spot_market_candles",
            ["symbol", "timeframe", "close_time"],
        )

    _add_event_identity_columns(bind, tables)
    _create_orderbook_snapshots(tables)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "orderbook_snapshots" in tables:
        indexes = {
            item["name"] for item in inspector.get_indexes("orderbook_snapshots")
        }
        if "ix_orderbook_snapshots_lookup" in indexes:
            op.drop_index(
                "ix_orderbook_snapshots_lookup",
                table_name="orderbook_snapshots",
            )
        if "ix_orderbook_snapshots_symbol" in indexes:
            op.drop_index(
                "ix_orderbook_snapshots_symbol",
                table_name="orderbook_snapshots",
            )
        op.drop_table("orderbook_snapshots")
    if "spot_market_candles" in tables:
        indexes = {
            item["name"] for item in inspector.get_indexes("spot_market_candles")
        }
        if "ix_spot_market_candles_lookup" in indexes:
            op.drop_index(
                "ix_spot_market_candles_lookup",
                table_name="spot_market_candles",
            )
        if "ix_spot_market_candles_symbol" in indexes:
            op.drop_index(
                "ix_spot_market_candles_symbol",
                table_name="spot_market_candles",
            )
        op.drop_table("spot_market_candles")

    if "funding_rates" in tables:
        indexes = {item["name"] for item in inspector.get_indexes("funding_rates")}
        if "uq_funding_rates_symbol_event" in indexes:
            op.drop_index(
                "uq_funding_rates_symbol_event",
                table_name="funding_rates",
            )

    _drop_event_identity_columns(inspector, tables)


def _add_event_identity_columns(bind, tables):
    if "whale_trades" in tables:
        columns = {
            item["name"] for item in sa.inspect(bind).get_columns("whale_trades")
        }
        if "venue" not in columns:
            op.add_column(
                "whale_trades",
                sa.Column(
                    "venue",
                    sa.String(length=20),
                    nullable=False,
                    server_default="BINANCE",
                ),
            )
        if "exchange_trade_id" not in columns:
            op.add_column(
                "whale_trades",
                sa.Column("exchange_trade_id", sa.String(length=40), nullable=True),
            )
        indexes = {
            item["name"] for item in sa.inspect(bind).get_indexes("whale_trades")
        }
        if "uq_whale_trades_exchange_event" not in indexes:
            op.create_index(
                "uq_whale_trades_exchange_event",
                "whale_trades",
                ["venue", "symbol", "exchange_trade_id"],
                unique=True,
            )

    if "liquidations" in tables:
        columns = {
            item["name"] for item in sa.inspect(bind).get_columns("liquidations")
        }
        if "venue" not in columns:
            op.add_column(
                "liquidations",
                sa.Column(
                    "venue",
                    sa.String(length=20),
                    nullable=False,
                    server_default="BINANCE",
                ),
            )
        if "exchange_event_id" not in columns:
            op.add_column(
                "liquidations",
                sa.Column("exchange_event_id", sa.String(length=40), nullable=True),
            )
        if "value_usd" not in columns:
            op.add_column(
                "liquidations",
                sa.Column("value_usd", sa.Float(), nullable=True),
            )
        indexes = {
            item["name"] for item in sa.inspect(bind).get_indexes("liquidations")
        }
        if "uq_liquidations_exchange_event" not in indexes:
            op.create_index(
                "uq_liquidations_exchange_event",
                "liquidations",
                ["venue", "symbol", "exchange_event_id"],
                unique=True,
            )


def _create_orderbook_snapshots(tables):
    if "orderbook_snapshots" in tables:
        return
    op.create_table(
        "orderbook_snapshots",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("venue", sa.String(length=20), nullable=False),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("event_time", sa.DateTime(), nullable=False),
        sa.Column("last_update_id", sa.String(length=40), nullable=False),
        sa.Column("best_bid", sa.Float(), nullable=False),
        sa.Column("best_ask", sa.Float(), nullable=False),
        sa.Column("mid_price", sa.Float(), nullable=False),
        sa.Column("spread_percent", sa.Float(), nullable=False),
        sa.Column("bid_depth_05pct", sa.Float(), nullable=False),
        sa.Column("ask_depth_05pct", sa.Float(), nullable=False),
        sa.Column("bid_depth_1pct", sa.Float(), nullable=False),
        sa.Column("ask_depth_1pct", sa.Float(), nullable=False),
        sa.Column("bid_depth_2pct", sa.Float(), nullable=False),
        sa.Column("ask_depth_2pct", sa.Float(), nullable=False),
        sa.Column("imbalance_percent", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "venue",
            "symbol",
            "last_update_id",
            name="uq_orderbook_snapshot_exchange_update",
        ),
    )
    op.create_index(
        "ix_orderbook_snapshots_symbol",
        "orderbook_snapshots",
        ["symbol"],
    )
    op.create_index(
        "ix_orderbook_snapshots_lookup",
        "orderbook_snapshots",
        ["symbol", "event_time"],
    )

def _drop_event_identity_columns(inspector, tables):
    for table_name, index_name, columns in (
        (
            "liquidations",
            "uq_liquidations_exchange_event",
            ("value_usd", "exchange_event_id", "venue"),
        ),
        (
            "whale_trades",
            "uq_whale_trades_exchange_event",
            ("exchange_trade_id", "venue"),
        ),
    ):
        if table_name not in tables:
            continue
        indexes = {
            item["name"] for item in inspector.get_indexes(table_name)
        }
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
        existing_columns = {
            item["name"] for item in inspector.get_columns(table_name)
        }
        for column in columns:
            if column in existing_columns:
                op.drop_column(table_name, column)
