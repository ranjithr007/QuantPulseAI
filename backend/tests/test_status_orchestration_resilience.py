from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.api.v1.scheduler_api import list_jobs
from app.api.v1.scheduler_api import scheduler_status
from app.api.v1.scheduler_api import start_scheduler_endpoint
from app.api.v2.fusion_ai_api import fusion
from app.api.v2.master_ai_v2_api import build_master_ai_response


def test_scheduler_list_jobs_returns_structured_failure():
    with patch("app.api.v1.scheduler_api.get_settings", side_effect=RuntimeError("boom")):
        payload = list_jobs()

    assert payload["status"] == "FAILED"
    assert payload["operation"] == "jobs"
    assert payload["jobs"] == []
    assert payload["error"] == "boom"


def test_scheduler_status_returns_structured_failure():
    with patch("app.scheduler.scheduler.get_scheduler", side_effect=RuntimeError("boom")):
        payload = scheduler_status()

    assert payload["status"] == "FAILED"
    assert payload["operation"] == "status"
    assert payload["jobs"] == []
    assert payload["error"] == "boom"


def test_scheduler_start_returns_structured_failure():
    with patch("app.scheduler.scheduler.start_scheduler", side_effect=RuntimeError("boom")), patch(
        "app.scheduler.scheduler.get_scheduler",
        return_value=Mock(running=False),
    ):
        payload = start_scheduler_endpoint(None)

    assert payload["status"] == "FAILED"
    assert payload["operation"] == "start"
    assert payload["jobs"] == []
    assert payload["error"] == "boom"


def test_master_ai_v2_returns_structured_failure_when_inputs_fail():
    fake_db = Mock()

    with patch("app.api.v2.master_ai_v2_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v2.master_ai_v2_api.get_ai_inputs",
        side_effect=RuntimeError("boom"),
    ):
        payload = build_master_ai_response("BTCUSDT", "5m")

    assert payload["status"] == "FAILED"
    assert payload["signal"] == "WAIT"
    assert payload["error"] == "boom"
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_master_ai_v2_includes_fusion_contract_on_success():
    fake_db = Mock()
    candle_time = datetime(2026, 6, 24, 3, 0, 0)
    candle = SimpleNamespace(
        close_price=100.0,
        candle_time=candle_time,
        close_time=candle_time,
    )
    feature = Mock(ATR=1.5, CreatedAt=datetime(2026, 6, 24, 2, 59, 0))
    regime = Mock(CreatedAt=datetime(2026, 6, 24, 2, 59, 0))
    orderflow = Mock(CreatedAt=datetime(2026, 6, 24, 2, 59, 0))
    smc = Mock(created_at=datetime(2026, 6, 24, 2, 59, 0))
    result = {
        "signal": "LONG",
        "bias": "LONG",
        "confidence": 82,
        "score": 82,
        "reasons": ["ok"],
        "scoring_profile": {
            "components": [{"name": "feature", "normalized_weight": 1.0}],
        },
    }

    with patch("app.api.v2.master_ai_v2_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v2.master_ai_v2_api.get_ai_inputs",
        return_value={"feature": feature, "regime": regime, "orderflow": orderflow, "smc": smc},
    ), patch(
        "app.api.v2.master_ai_v2_api.get_latest_candle",
        return_value=candle,
    ), patch(
        "app.api.v2.master_ai_v2_api.generate_master_signal",
        return_value=result,
    ), patch(
        "app.api.v2.master_ai_v2_api.build_trade_plan",
        return_value={"entry": 100.0, "target1": 102.0, "atr": 1.5},
    ), patch(
        "app.api.v2.master_ai_v2_api.validate_trade_plan_direction",
        return_value={"is_valid": True, "errors": []},
    ), patch(
        "app.api.v2.master_ai_v2_api.validate_signal",
        return_value={"quality_score": 80, "decision": "TAKE_TRADE", "warnings": []},
    ), patch(
        "app.api.v2.master_ai_v2_api.build_contradiction_report",
        return_value={"status": "OK"},
    ), patch(
        "app.api.v2.master_ai_v2_api.build_probability_profile",
        return_value={"status": "OK"},
    ), patch(
        "app.api.v2.master_ai_v2_api.build_data_quality_observability",
        return_value={"source": "data_quality_ledger", "decision": "ALLOW", "blocked": False},
    ), patch(
        "app.api.v2.master_ai_v2_api.RiskEngine",
    ) as risk_engine_cls:
        risk_engine = risk_engine_cls.return_value
        risk_engine.analyze.return_value = {"risk": "MEDIUM"}
        payload = build_master_ai_response("BTCUSDT", "5m", stale_after_seconds=300)

    contract = payload["fusion_contract"]
    assert contract["source"] == "master_ai_fusion_contract"
    assert contract["signal"] == "LONG"
    assert contract["risk_level"] == "LOW"
    assert contract["risk_management"]["risk"] == "MEDIUM"
    assert contract["data_quality"]["source"] == "data_quality_ledger"
    assert contract["thesis"]["source"] == "thesis_preview"
    assert contract["scenario"]["source"] == "scenario_preview"
    assert contract["scenario"]["primary_path"]["name"] == "WAIT"
    assert contract["entry_block_reason"] is None
    assert contract["next_review_at"].isoformat().startswith("2026-06-24T03:05:00")
    assert contract["missing_components"] == []
    assert fake_db.close.called


def test_fusion_v2_returns_structured_failure_when_service_fails():
    fake_db = Mock()

    with patch("app.api.v2.fusion_ai_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v2.fusion_ai_api.service.generate",
        side_effect=RuntimeError("boom"),
    ):
        payload = fusion("BTCUSDT")

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert fake_db.rollback.called
    assert fake_db.close.called
