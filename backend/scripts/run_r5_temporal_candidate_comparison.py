"""Guard and run the R5 candidate comparison on a later temporal freeze."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.backtesting.frozen_replay_runner import load_frozen_replay_context
from app.backtesting.frozen_replay_runner import run_frozen_walk_forward
from app.backtesting.portfolio_replay import build_portfolio_replay
from app.backtesting.strategy_family_research import build_r5_strategy_evidence
from scripts.run_r5_multisymbol_holdout import (
    DOGE_CALIBRATION_FOLD_PARAMETERS,
    _holdout_gates,
)


INSPECTED_CUTOFF = datetime(2026, 7, 27, 15, tzinfo=timezone.utc)
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT")
PROFILES = (
    "RESEARCH_CALIBRATION",
    "BEAR_RALLY_EXHAUSTION",
    "PROFIT_PROTECTION_RESEARCH",
)
TRAIN_CANDLES = 4320
TEST_CANDLES = 1440
WINDOW_CANDLES = TRAIN_CANDLES + TEST_CANDLES


def assess_temporal_readiness(*, input_dir, as_of, symbols, window_candles=WINDOW_CANDLES):
    input_root = Path(input_dir)
    as_of = _utc(as_of)
    symbol_checks = {}
    for symbol in symbols:
        path = input_root / f"{symbol}_1h_{as_of.strftime('%Y%m%dT%H%M%SZ')}.json"
        reasons = []
        details = {
            "path": str(path),
            "exists": path.exists(),
            "candle_count": 0,
            "test_start": None,
            "latest_candle": None,
        }
        if not path.exists():
            reasons.append("FROZEN_INPUT_MISSING")
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            candles = list(payload.get("candles") or [])
            details["candle_count"] = len(candles)
            if payload.get("contract") != "r5_frozen_replay_input_v1":
                reasons.append("INPUT_CONTRACT_INVALID")
            if str(payload.get("symbol") or "").upper() != symbol:
                reasons.append("SYMBOL_IDENTITY_MISMATCH")
            if payload.get("timeframe") != "1h":
                reasons.append("TIMEFRAME_IDENTITY_MISMATCH")
            payload_as_of = _utc(payload.get("as_of"))
            if payload_as_of != as_of:
                reasons.append("CUTOFF_IDENTITY_MISMATCH")
            if len(candles) < int(window_candles):
                reasons.append("INSUFFICIENT_WINDOW_CANDLES")
            else:
                selected = candles[-int(window_candles) :]
                test_start = _candle_timestamp(selected[TRAIN_CANDLES])
                latest = _candle_timestamp(selected[-1])
                details["test_start"] = _iso(test_start)
                details["latest_candle"] = _iso(latest)
                if test_start is None or test_start <= INSPECTED_CUTOFF:
                    reasons.append("TEST_WINDOW_OVERLAPS_INSPECTED_HISTORY")
                if latest is None or latest > as_of:
                    reasons.append("LATEST_CANDLE_AFTER_FROZEN_CUTOFF")
        symbol_checks[symbol] = {
            **details,
            "status": "READY" if not reasons else "BLOCKED",
            "reasons": reasons,
        }

    global_reasons = []
    if as_of <= INSPECTED_CUTOFF:
        global_reasons.append("CUTOFF_NOT_LATER_THAN_INSPECTED_WINDOW")
    if any(check["status"] != "READY" for check in symbol_checks.values()):
        global_reasons.append("ONE_OR_MORE_SYMBOLS_NOT_READY")
    return {
        "contract": "r5_temporal_candidate_readiness_v1",
        "status": "READY" if not global_reasons else "BLOCKED",
        "production_eligible": False,
        "as_of": as_of.isoformat(),
        "inspected_cutoff": INSPECTED_CUTOFF.isoformat(),
        "required_window": {
            "train_candles": TRAIN_CANDLES,
            "test_candles": TEST_CANDLES,
            "total_candles": int(window_candles),
            "test_must_start_after": INSPECTED_CUTOFF.isoformat(),
        },
        "profiles": list(PROFILES),
        "symbols": list(symbols),
        "reasons": global_reasons,
        "symbol_checks": symbol_checks,
    }


def run_comparison(
    *,
    input_dir,
    output_path,
    checkpoint_dir,
    as_of,
    symbols=DEFAULT_SYMBOLS,
    window_candles=WINDOW_CANDLES,
):
    readiness = assess_temporal_readiness(
        input_dir=input_dir,
        as_of=as_of,
        symbols=symbols,
        window_candles=window_candles,
    )
    if readiness["status"] != "READY":
        raise RuntimeError(
            "Temporal candidate comparison is blocked: "
            + ", ".join(readiness["reasons"])
        )

    profile_results = {}
    for profile in PROFILES:
        symbol_results = {}
        for symbol in symbols:
            checkpoint = (
                Path(checkpoint_dir)
                / profile
                / f"{symbol}_1h_{_utc(as_of).strftime('%Y%m%dT%H%M%SZ')}.json"
            )
            result = _load_checkpoint(
                checkpoint,
                symbol=symbol,
                profile=profile,
                as_of=as_of,
                window_candles=window_candles,
            )
            if result is None:
                result = _run_profile_symbol(
                    input_dir=input_dir,
                    symbol=symbol,
                    profile=profile,
                    as_of=as_of,
                    window_candles=window_candles,
                )
                _write_checkpoint(
                    checkpoint,
                    symbol=symbol,
                    profile=profile,
                    as_of=as_of,
                    window_candles=window_candles,
                    result=result,
                )
            symbol_results[symbol] = result
        profile_results[profile] = _aggregate_profile(symbol_results, symbols)

    control = profile_results["RESEARCH_CALIBRATION"]
    for profile, result in profile_results.items():
        result["delta_vs_control"] = _comparison_delta(result, control)
    payload = {
        "contract": "r5_temporal_candidate_comparison_v1",
        "status": "RESEARCH_COMPARISON_COMPLETE",
        "production_eligible": False,
        "automatic_winner_selection": False,
        "readiness": readiness,
        "profiles": profile_results,
        "policy": {
            "parameter_tuning_from_this_report": "PROHIBITED",
            "promotion_requires_governance_review": True,
            "isolated_candidates_must_pass_before_combination": True,
            "frozen_fold_parameters": DOGE_CALIBRATION_FOLD_PARAMETERS[:1],
        },
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def _run_profile_symbol(*, input_dir, symbol, profile, as_of, window_candles):
    as_of = _utc(as_of)
    path = (
        Path(input_dir)
        / f"{symbol}_1h_{as_of.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    context, payload = load_frozen_replay_context(path)
    context["candles"] = context["candles"][-int(window_candles) :]
    common = {
        "limit": int(window_candles),
        "stop_grid": (0.75, 1.0, 1.25, 1.5),
        "target_grid": (1.5, 2.0, 2.5, 3.0),
        "train_size": TRAIN_CANDLES,
        "test_size": TEST_CANDLES,
        "step_size": TEST_CANDLES,
        "mode": "EXPANDING",
        "min_train_trades": 1,
        "initial_capital": 10_000,
        "position_size_percent": 100,
        "strategy": profile,
        "as_of_timestamp": as_of,
        "frozen_fold_parameters": DOGE_CALIBRATION_FOLD_PARAMETERS[:1],
    }
    baseline = run_frozen_walk_forward(
        context,
        symbol=symbol,
        timeframe="1h",
        signal="SHORT",
        fee_bps=4,
        slippage_bps=2,
        **common,
    )
    adverse = run_frozen_walk_forward(
        context,
        symbol=symbol,
        timeframe="1h",
        signal="SHORT",
        fee_bps=8,
        slippage_bps=4,
        **common,
    )
    return {
        "input": {
            key: payload.get(key)
            for key in ("contract", "captured_at", "symbol", "timeframe", "as_of", "limit")
        },
        "baseline": baseline,
        "adverse_cost": adverse,
        "evidence": build_r5_strategy_evidence(
            baseline,
            adverse_cost_result=adverse,
        ),
    }


def _aggregate_profile(symbol_results, symbols):
    options = {
        "initial_capital": 10_000,
        "max_open_positions": len(symbols),
        "max_gross_exposure_percent": len(symbols) * 100,
        "max_cluster_exposure_percent": 100,
    }
    baseline = build_portfolio_replay(
        {
            symbol: result["baseline"]["out_of_sample"]
            for symbol, result in symbol_results.items()
        },
        **options,
    )
    adverse = build_portfolio_replay(
        {
            symbol: result["adverse_cost"]["out_of_sample"]
            for symbol, result in symbol_results.items()
        },
        **options,
    )
    return {
        "production_eligible": False,
        "gates": _holdout_gates(symbol_results, baseline, adverse),
        "portfolio_baseline": baseline,
        "portfolio_adverse_cost": adverse,
        "symbol_results": symbol_results,
    }


def _comparison_delta(result, control):
    baseline = result["portfolio_baseline"]
    control_baseline = control["portfolio_baseline"]
    adverse = result["portfolio_adverse_cost"]
    control_adverse = control["portfolio_adverse_cost"]
    return {
        "total_trades": int(baseline.get("total_trades") or 0)
        - int(control_baseline.get("total_trades") or 0),
        "profit_factor": _difference(
            baseline.get("profit_factor"), control_baseline.get("profit_factor")
        ),
        "expectancy_percent": _difference(
            baseline.get("expectancy_percent"),
            control_baseline.get("expectancy_percent"),
        ),
        "max_drawdown_percent": _difference(
            baseline.get("max_drawdown_percent"),
            control_baseline.get("max_drawdown_percent"),
        ),
        "adverse_expectancy_percent": _difference(
            adverse.get("expectancy_percent"),
            control_adverse.get("expectancy_percent"),
        ),
    }


def _load_checkpoint(path, *, symbol, profile, as_of, window_candles):
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("contract") != "r5_temporal_profile_checkpoint_v1"
        or payload.get("symbol") != symbol
        or payload.get("profile") != profile
        or payload.get("as_of") != _utc(as_of).isoformat()
        or payload.get("window_candles") != int(window_candles)
    ):
        return None
    return payload.get("result")


def _write_checkpoint(path, *, symbol, profile, as_of, window_candles, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract": "r5_temporal_profile_checkpoint_v1",
        "symbol": symbol,
        "profile": profile,
        "as_of": _utc(as_of).isoformat(),
        "window_candles": int(window_candles),
        "result": result,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _difference(value, control):
    if value is None or control is None:
        return None
    return round(float(value) - float(control), 4)


def _candle_timestamp(candle):
    return _utc(
        candle.get("candle_time")
        or candle.get("open_time")
        or candle.get("close_time")
    )


def _utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value):
    return value.isoformat() if value is not None else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--input-dir", default="outputs/r5_frozen_inputs")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument(
        "--readiness-output",
        default="outputs/r5_temporal_candidate_readiness.json",
    )
    parser.add_argument(
        "--output",
        default="outputs/r5_frozen_runs/r5_temporal_candidate_comparison.json",
    )
    parser.add_argument(
        "--checkpoint-dir",
        default="outputs/r5_frozen_runs/r5_temporal_candidate_checkpoints",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    as_of = _utc(args.as_of)
    readiness = assess_temporal_readiness(
        input_dir=args.input_dir,
        as_of=as_of,
        symbols=tuple(args.symbols),
    )
    readiness_path = Path(args.readiness_output)
    readiness_path.parent.mkdir(parents=True, exist_ok=True)
    readiness_path.write_text(
        json.dumps(readiness, indent=2, default=str),
        encoding="utf-8",
    )
    if not args.execute:
        print(json.dumps(readiness, indent=2))
        return
    result = run_comparison(
        input_dir=args.input_dir,
        output_path=args.output,
        checkpoint_dir=args.checkpoint_dir,
        as_of=as_of,
        symbols=tuple(args.symbols),
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "profiles": list(result["profiles"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
