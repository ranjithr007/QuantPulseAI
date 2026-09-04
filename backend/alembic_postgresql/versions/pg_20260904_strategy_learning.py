"""add automatic paper strategy learning and correct result labels

Revision ID: pg_20260904_strategy_learning
Revises: pg_20260903_participation_idx
"""

from pathlib import Path
import importlib.util


revision = "pg_20260904_strategy_learning"
down_revision = "pg_20260903_participation_idx"
branch_labels = None
depends_on = None


def _shared_module(filename, module_name):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_result_fix = _shared_module(
    "v0n1o2p3q4r5_fix_strategy_trade_result_labels.py",
    "quantpulse_strategy_result_fix",
)
_learning = _shared_module(
    "w1o2p3q4r5s6_add_strategy_learning.py",
    "quantpulse_strategy_learning_schema",
)


def upgrade():
    _result_fix.upgrade()
    _learning.upgrade()


def downgrade():
    _learning.downgrade()
