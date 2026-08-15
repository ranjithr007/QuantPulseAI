"""add INR paper wallet ledger

Revision ID: pg_20260815_wallet_ledger
Revises: pg_20260815_exit_checkpoint
"""

from pathlib import Path
import importlib.util


revision = "pg_20260815_wallet_ledger"
down_revision = "pg_20260815_exit_checkpoint"
branch_labels = None
depends_on = None


_shared_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "k9c0d1e2f3a4_add_inr_paper_wallet_ledger.py"
)
_spec = importlib.util.spec_from_file_location("quantpulse_inr_wallet_migration", _shared_path)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


def upgrade():
    _shared.upgrade()


def downgrade():
    _shared.downgrade()
