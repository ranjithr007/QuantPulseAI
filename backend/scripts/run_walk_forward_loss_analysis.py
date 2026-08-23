"""Generate an evidence-only loss-cluster audit from one walk-forward run."""

from __future__ import annotations

import argparse
import json

from app.backtesting.loss_cluster_analysis import generate_loss_cluster_artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("consolidated_report")
    parser.add_argument("--output-dir")
    arguments = parser.parse_args()
    result = generate_loss_cluster_artifacts(
        arguments.consolidated_report,
        output_dir=arguments.output_dir,
    )
    report = result["report"]
    print(
        json.dumps(
            {
                "status": "COMPLETED",
                "trades": report["overall"]["trade_count"],
                "hypotheses": len(report["research_hypotheses"]),
                "json_path": result["json_path"],
                "markdown_path": result["markdown_path"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
