"""Add opportunity lookup index and cross-process exit heartbeat."""

from pathlib import Path
import importlib.util


revision = "pg_20260914_operational_ready"
down_revision = "pg_20260907_exit_evidence"
branch_labels = None
depends_on = None


def _shared_module(filename, module_name):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_opportunity_index = _shared_module(
    "y3q4r5s6t7u8_add_opportunity_history_index.py",
    "quantpulse_opportunity_history_index",
)
_fast_exit_heartbeat = _shared_module(
    "z4r5s6t7u8v9_add_fast_exit_heartbeat.py",
    "quantpulse_fast_exit_heartbeat",
)


def upgrade():
    _opportunity_index.upgrade()
    _fast_exit_heartbeat.upgrade()


def downgrade():
    _fast_exit_heartbeat.downgrade()
    _opportunity_index.downgrade()
