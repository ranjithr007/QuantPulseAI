"""Preview the disabled-by-default pipeline retention policy."""

import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.jobs.pipeline_retention_job import run_pipeline_retention_job  # noqa: E402


if __name__ == "__main__":
    print(json.dumps(run_pipeline_retention_job(), default=str, indent=2))
