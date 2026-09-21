import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from app.backtesting import spot_pullback_research as research


def test_context_only_btc_never_opens_a_trade(monkeypatch):
    index = pd.date_range("2026-01-01", periods=16, freq="15min", tz="UTC")
    frame = pd.DataFrame({"open": 100., "close": 100., "high": 100.5,
                          "low": 99.5, "quote_volume": 1e7}, index=index)
    def features(f, btc_frame=None):
        out = f.copy()
        out.index += research.BAR
        out["signal"] = out.index == index[2]
        out["stop"], out["atr"] = 97.5, 1.2
        out["turnover"], out["trend_exit"] = 1e9, False
        return out
    monkeypatch.setattr(research, "build_features", features)
    inputs = {"BTCUSDT": frame, "SOLUSDT": frame}
    result = research.run_screen(inputs, start=index[2], end=index[12], tradable_symbols=["SOLUSDT"])
    assert result["symbols"] == ["SOLUSDT"]
    assert len(result["trades"]) == 1
    assert result["trades"][0]["symbol"] == "SOLUSDT"
    assert result["metrics"]["net_pnl"] == pytest.approx(result["trades"][0]["net_pnl"])
    with pytest.raises(ValueError, match="Tradable"):
        research.run_screen(inputs, start=index[2], end=index[12], tradable_symbols=["XRPUSDT"])
    with pytest.raises(ValueError, match="Tradable"):
        research.run_screen(inputs, start=index[2], end=index[12], tradable_symbols=[])


def test_archive_symbol_names_cannot_inject_paths():
    path = Path(__file__).resolve().parents[1] / "scripts/run_spot_pullback_research.py"
    spec = importlib.util.spec_from_file_location("archive_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.validate_symbols(["BTCUSDT", "SOLUSDT"]) == ("BTCUSDT", "SOLUSDT")
    for values in (["../../BTCUSDT"], ["BTCUSDT", "BTCUSDT"], [], ["btcusdt"]):
        with pytest.raises(ValueError):
            module.validate_symbols(values)


def test_registration_detects_plan_tampering_and_policy_drift(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("transfer_runner_test", root / "scripts/validate_spot_trend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = json.loads(module.PLAN.read_text())
    temporary_plan = tmp_path / "plan.json"
    temporary_plan.write_text(json.dumps(plan))
    monkeypatch.setattr(module, "PLAN", temporary_plan)
    reference = tmp_path / "reference"
    reference.mkdir()
    feature_source = str(Path("app/backtesting/spot_pullback_comparison.py"))
    (reference / "registration.json").write_text(json.dumps({
        "plan": {"candidates": [plan["policy"]]},
        "source_sha256": {feature_source: module.digest(root / feature_source)}
    }))
    output = tmp_path / "registered"
    module.register(output, reference)
    assert module.verify(output)["frozen_signal_source_verified"] is True
    temporary_plan.write_text(temporary_plan.read_text() + "\n")
    with pytest.raises(ValueError, match="plan changed"):
        module.verify(output)
    plan["policy"]["entry_cap_atr"] = .1
    temporary_plan.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="policy differs"):
        module.register(tmp_path / "changed", reference)
