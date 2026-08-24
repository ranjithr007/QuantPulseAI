"""Write an outcome-blind readiness report for the frozen prospective holdout."""

import argparse
import json
from pathlib import Path

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
