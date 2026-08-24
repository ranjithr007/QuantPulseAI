"""Write an outcome-blind readiness report for the frozen prospective holdout."""

import argparse
import json
import sys
from pathlib import Path

# Direct execution sets sys.path to /app/scripts rather than /app.  Add the
# backend root so the documented `python scripts/...py` command works in the
# Railway image without requiring an external PYTHONPATH setting.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.backtesting.prospective_holdout_readiness import build_current_data_readiness
from app.database.sqlserver import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="outputs/prospective_holdout_data_readiness.json",
    )
    arguments = parser.parse_args()
    with SessionLocal() as session:
        report = build_current_data_readiness(session)
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
