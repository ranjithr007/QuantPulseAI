"""Diagnose loss clusters in the sealed R5 untouched-symbol holdout."""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def analyze_holdout(payload):
    trades = []
    for symbol, result in (payload.get("symbol_results") or {}).items():
        for raw_trade in (
            (result.get("baseline") or {})
            .get("out_of_sample", {})
            .get("trades", [])
        ):
            trade = dict(raw_trade)
            trade["symbol"] = symbol
            trade["stack_state"] = (
                ((trade.get("timeframe_stack") or {}).get("confirmation") or {}).get(
                    "stack_state"
                )
                or "UNKNOWN"
            )
            trade["confidence_band"] = _confidence_band(trade.get("confidence"))
            trades.append(trade)

    dimensions = {
        "symbol": _group_summary(trades, lambda trade: trade["symbol"]),
        "regime": _group_summary(
            trades, lambda trade: trade.get("regime") or "UNKNOWN"
        ),
        "stack_state": _group_summary(
            trades, lambda trade: trade["stack_state"]
        ),
        "confidence_band": _group_summary(
            trades, lambda trade: trade["confidence_band"]
        ),
        "regime_stack": _group_summary(
            trades,
            lambda trade: (
                f"{trade.get('regime') or 'UNKNOWN'}"
                f"::{trade['stack_state']}"
            ),
        ),
        "loss_class": _group_summary(
            trades, lambda trade: trade.get("loss_class") or "UNKNOWN"
        ),
    }
    stopped = [trade for trade in trades if trade.get("exit_reason") == "STOP"]
    recovered = [
        trade
        for trade in stopped
        if bool((trade.get("excursions") or {}).get("post_stop_target_recovered"))
    ]
    harmful = []
    for dimension in ("symbol", "regime", "stack_state", "confidence_band", "regime_stack"):
        for row in dimensions[dimension]:
            if row["trades"] >= 3 and row["net_pnl"] < 0:
                harmful.append({"dimension": dimension, **row})
    harmful.sort(key=lambda row: (row["net_pnl"], -row["trades"], row["key"]))

    return {
        "contract": "r5_holdout_loss_cluster_diagnostic_v1",
        "source_contract": payload.get("contract"),
        "source_status": payload.get("status"),
        "production_eligible": False,
        "policy": {
            "diagnostic_only": True,
            "parameter_changes_from_this_window": "PROHIBITED",
            "future_temporal_holdout_remains_untouched": True,
        },
        "overall": _summarize(trades),
        "stop_recovery": {
            "stopped_trades": len(stopped),
            "post_stop_target_recovered": len(recovered),
            "recovery_rate_percent": _percent(len(recovered), len(stopped)),
        },
        "dimensions": dimensions,
        "harmful_clusters": harmful,
    }


def _group_summary(trades, key_fn):
    grouped = defaultdict(list)
    for trade in trades:
        grouped[str(key_fn(trade))].append(trade)
    rows = [{"key": key, **_summarize(items)} for key, items in grouped.items()]
    return sorted(rows, key=lambda row: (-row["trades"], row["key"]))


def _summarize(trades):
    wins = [trade for trade in trades if float(trade.get("pnl") or 0) > 0]
    losses = [trade for trade in trades if float(trade.get("pnl") or 0) < 0]
    gross_profit = sum(float(trade.get("pnl") or 0) for trade in wins)
    gross_loss = abs(sum(float(trade.get("pnl") or 0) for trade in losses))
    pnl_values = [float(trade.get("pnl") or 0) for trade in trades]
    pnl_percent_values = [float(trade.get("pnl_percent") or 0) for trade in trades]
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _percent(len(wins), len(trades)),
        "net_pnl": round(sum(pnl_values), 4),
        "expectancy_percent": (
            round(sum(pnl_percent_values) / len(pnl_percent_values), 4)
            if pnl_percent_values
            else 0.0
        ),
        "profit_factor": (
            round(gross_profit / gross_loss, 4)
            if gross_loss
            else None if not gross_profit else "INF"
        ),
    }


def _confidence_band(value):
    confidence = float(value or 0)
    if confidence < 60:
        return "LT_60"
    if confidence < 65:
        return "60_TO_64_99"
    if confidence < 70:
        return "65_TO_69_99"
    return "GE_70"


def _percent(numerator, denominator):
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=(
            "outputs/r5_frozen_runs/"
            "multisymbol_short_holdout_20260727T150000Z.json"
        ),
    )
    parser.add_argument(
        "--output",
        default=(
            "outputs/r5_frozen_runs/"
            "multisymbol_short_holdout_clusters_20260727T150000Z.json"
        ),
    )
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    diagnostic = analyze_holdout(payload)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(diagnostic, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "overall": diagnostic["overall"],
                "stop_recovery": diagnostic["stop_recovery"],
                "top_harmful_clusters": diagnostic["harmful_clusters"][:10],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
