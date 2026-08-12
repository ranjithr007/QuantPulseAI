from scripts import run_gate_ablation_validation
from scripts.run_gate_ablation_validation import _build_research_context, _record, _run_symbol


def test_ablation_record_preserves_score_and_overlap_diagnostics():
    distributions = {
        "final_score": {
            "count": 2,
            "minimum": 40,
            "maximum": 60,
            "average": 50,
            "value_sum": 100,
            "buckets": {"40-49": 1, "60-69": 1},
        }
    }
    master_diagnostics = {
        "regime_gate_pass_decisions": {
            "evaluated": 2,
            "signals": {"WAIT": 2},
            "biases": {"NEUTRAL": 2},
            "score_distribution": distributions["final_score"],
            "components": {},
        }
    }
    result = {
        "validation_status": "VALID",
        "fold_count": 1,
        "out_of_sample": {
            "total_trades": 0,
            "gate_diagnostics": {
                "evaluated_decisions": 2,
                "independent_gate_pass_counts": {"MARKET_DATA": 2},
                "independent_gate_pass_percentages": {"MARKET_DATA": 100},
                "rejection_combinations": {"REGIME_NOT_BULLISH": 2},
                "feature_score_distributions": distributions,
                "master_signal_diagnostics": master_diagnostics,
            },
        },
    }

    record = _record(
        "BTCUSDT",
        "4h",
        "LONG",
        "STRICT_BASELINE",
        {"description": "strict", "production_eligible": True},
        result,
    )

    assert record["independent_gate_pass_counts"] == {"MARKET_DATA": 2}
    assert record["rejection_combinations"] == {"REGIME_NOT_BULLISH": 2}
    assert record["feature_score_distributions"] == distributions
    assert record["master_signal_diagnostics"] == master_diagnostics


def test_research_context_rebuilds_the_decision_chain_with_candidate_detector(monkeypatch):
    captured = {}
    resolver = type("Resolver", (), {"feature_resolver": object()})()

    def build(symbol, stack_candles, **options):
        captured.update(symbol=symbol, stack_candles=stack_candles, **options)
        return resolver

    monkeypatch.setattr(
        run_gate_ablation_validation.trade_simulator,
        "_build_in_memory_stack_resolver",
        build,
    )
    context = {
        "stack_candles": {"4h": [object()]},
        "derivative_history": {"funding": []},
        "stack_resolver": object(),
        "feature_resolver": object(),
    }

    rebuilt = _build_research_context(
        context,
        symbol="BTCUSDT",
        timeframe="4h",
        spec={
            "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
            "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        },
    )

    assert captured["symbol"] == "BTCUSDT"
    assert captured["regime_detector"].__name__ == (
        "detect_regime_momentum_boundary_research"
    )
    assert captured["transition_policy"].__name__ == (
        "direction_aware_transition_research"
    )
    assert rebuilt["stack_resolver"] is resolver
    assert rebuilt["feature_resolver"] is resolver.feature_resolver


def test_detector_only_scope_uses_direct_research_context_path(monkeypatch):
    captured = []

    def execute(symbol, timeframe, side, **options):
        captured.append((symbol, timeframe, side, options))
        return {
            "validation_status": "VALID",
            "fold_count": 1,
            "out_of_sample": {"total_trades": 0, "gate_diagnostics": {}},
        }

    monkeypatch.setattr(
        run_gate_ablation_validation.trade_simulator,
        "execute_walk_forward",
        execute,
    )
    result = _run_symbol(
        {
            "symbol": "BTCUSDT",
            "timeframe": "4h",
            "signals": ("SHORT",),
            "profiles": ("MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",),
            "limit": 720,
            "train_size": 360,
            "test_size": 120,
            "step_size": 120,
            "as_of": "2026-08-11T11:00:00+00:00",
        }
    )

    assert result["status"] == "COMPLETED"
    assert len(captured) == 1
    options = captured[0][3]
    assert options["research_label"] == "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH"
    assert options["regime_detector"].__name__ == (
        "detect_regime_momentum_boundary_research"
    )


def test_direction_aware_scope_injects_research_transition_policy(monkeypatch):
    captured = []

    def execute(symbol, timeframe, side, **options):
        captured.append(options)
        return {
            "validation_status": "VALID",
            "fold_count": 1,
            "out_of_sample": {"total_trades": 0, "gate_diagnostics": {}},
        }

    monkeypatch.setattr(
        run_gate_ablation_validation.trade_simulator,
        "execute_walk_forward",
        execute,
    )
    result = _run_symbol(
        {
            "symbol": "BTCUSDT",
            "timeframe": "4h",
            "signals": ("LONG",),
            "profiles": ("DIRECTION_AWARE_HYSTERESIS_RESEARCH",),
            "limit": 720,
            "train_size": 360,
            "test_size": 120,
            "step_size": 120,
            "as_of": "2026-08-11T11:00:00+00:00",
        }
    )

    assert result["status"] == "COMPLETED"
    assert captured[0]["regime_detector"].__name__ == (
        "detect_regime_momentum_boundary_research"
    )
    assert captured[0]["transition_policy"].__name__ == (
        "direction_aware_transition_research"
    )


def test_directional_entry_scope_injects_research_gate_profile(monkeypatch):
    captured = []

    def execute(symbol, timeframe, side, **options):
        captured.append(options)
        return {
            "validation_status": "VALID",
            "fold_count": 1,
            "out_of_sample": {"total_trades": 0, "gate_diagnostics": {}},
        }

    monkeypatch.setattr(
        run_gate_ablation_validation.trade_simulator,
        "execute_walk_forward",
        execute,
    )
    result = _run_symbol(
        {
            "symbol": "BTCUSDT",
            "timeframe": "4h",
            "signals": ("LONG",),
            "profiles": ("DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",),
            "limit": 720,
            "train_size": 360,
            "test_size": 120,
            "step_size": 120,
            "as_of": "2026-08-11T11:00:00+00:00",
        }
    )

    assert result["status"] == "COMPLETED"
    assert captured[0]["research_gate_profile"] == (
        "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH"
    )


def test_confidence_calibration_profile_changes_only_minimum_confidence(monkeypatch):
    captured = []

    def execute(symbol, timeframe, side, **options):
        captured.append(options)
        return {
            "validation_status": "VALID",
            "fold_count": 1,
            "out_of_sample": {"total_trades": 0, "gate_diagnostics": {}},
        }

    monkeypatch.setattr(
        run_gate_ablation_validation.trade_simulator,
        "execute_walk_forward",
        execute,
    )
    result = _run_symbol(
        {
            "symbol": "BTCUSDT",
            "timeframe": "4h",
            "signals": ("LONG",),
            "profiles": ("DIRECTIONAL_CONFIDENCE_62_RESEARCH",),
            "limit": 720,
            "train_size": 360,
            "test_size": 120,
            "step_size": 120,
            "as_of": "2026-08-11T11:00:00+00:00",
        }
    )

    assert result["status"] == "COMPLETED"
    assert captured[0]["min_confidence"] == 62
    assert captured[0]["research_gate_profile"] == (
        "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH"
    )
    assert captured[0]["regime_detector"].__name__ == (
        "detect_regime_momentum_boundary_research"
    )
    assert captured[0]["transition_policy"].__name__ == (
        "direction_aware_transition_research"
    )


def test_single_risk_calibration_profile_forwards_both_confidence_boundaries(monkeypatch):
    captured = []

    def execute(symbol, timeframe, side, **options):
        captured.append(options)
        return {
            "validation_status": "VALID",
            "fold_count": 1,
            "out_of_sample": {"total_trades": 0, "gate_diagnostics": {}},
        }

    monkeypatch.setattr(
        run_gate_ablation_validation.trade_simulator,
        "execute_walk_forward",
        execute,
    )
    result = _run_symbol(
        {
            "symbol": "BTCUSDT",
            "timeframe": "4h",
            "signals": ("LONG",),
            "profiles": ("DIRECTIONAL_RISK_CONFIDENCE_45_RESEARCH",),
            "limit": 720,
            "train_size": 360,
            "test_size": 120,
            "step_size": 120,
            "as_of": "2026-08-11T11:00:00+00:00",
        }
    )

    assert result["status"] == "COMPLETED"
    assert captured[0]["min_confidence"] == 60
    assert captured[0]["risk_min_confidence"] == 45
    assert captured[0]["risk_confidence_scope"] == "DIRECTIONAL_PULLBACK_RANGE"
