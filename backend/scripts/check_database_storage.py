"""Print read-only PostgreSQL table-growth and retention telemetry."""

import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.database.runtime import engine  # noqa: E402
from app.observability.database_storage import build_database_storage_report  # noqa: E402


if __name__ == "__main__":
    print(
        json.dumps(
            build_database_storage_report(engine, get_settings()),
            default=str,
            indent=2,
        )
    )
