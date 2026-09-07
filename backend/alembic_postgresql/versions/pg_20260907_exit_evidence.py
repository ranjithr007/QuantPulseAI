"""Add paper execution evidence without rewriting existing positions."""
from pathlib import Path
import importlib.util

revision = "pg_20260907_exit_evidence"
down_revision = "pg_20260904_strategy_learning"
branch_labels = None
depends_on = None

_path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "x2p3q4r5s6t7_add_paper_execution_evidence.py"
_spec = importlib.util.spec_from_file_location("quantpulse_paper_execution_evidence", _path)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


def upgrade():
    _shared.upgrade()


def downgrade():
    _shared.downgrade()
