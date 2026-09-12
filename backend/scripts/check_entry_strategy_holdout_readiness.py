"""Print the outcome-blind V2F entry-strategy holdout readiness report."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.backtesting.entry_strategy_holdout_readiness import (
    build_current_entry_holdout_readiness,
)
from app.database.sqlserver import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        help="Optional ISO-8601 observation time for a reproducible readiness snapshot.",
    )
    parser.add_argument(
        "--manifest",
        help="Optional frozen V2F manifest path.",
    )
    parser.add_argument(
        "--output",
        default="outputs/entry_strategy_holdout_readiness_v2f.json",
    )
    arguments = parser.parse_args()
    observed_at = (
        datetime.fromisoformat(arguments.as_of.replace("Z", "+00:00"))
        if arguments.as_of
        else None
    )
    with SessionLocal() as session:
        report = build_current_entry_holdout_readiness(
            session,
            observed_at=observed_at,
            manifest_path=arguments.manifest,
        )
        session.rollback()
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
