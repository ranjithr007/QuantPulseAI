from unittest.mock import Mock, patch
from datetime import datetime

from app.api.v1.automation_api import AutomationSettingsUpdate
from app.api.v1.automation_api import read_automation_audit
from app.api.v1.automation_api import read_automation_settings
from app.api.v1.automation_api import write_automation_settings
from app.api.v1.orderflow_api import get_orderflow
from app.api.v1.regime_api import get_regime_catalog
from app.api.v1.regime_api import get_regime_summary
from app.api.v1.risk_api import get_risk_bundle
from app.api.v1.smc_api import get_smc
from app.api.v1.symbols_api import seed_default_symbols
from app.api.v1.symbols_api import list_symbols
from app.api.v1.thesis_api import get_latest_trade_thesis
from app.api.v1.thesis_api import get_thesis_snapshot_as_of_route
from app.api.v1.thesis_api import get_trade_thesis_lineage
from app.api.v1.thesis_api import get_trade_theses
from app.api.v1.trade_plan_api import get_trade_plan


def test_automation_read_settings_returns_failure_when_lookup_fails():
    fake_db = Mock()

    with patch("app.api.v1.automation_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.automation_api.get_automation_settings",
        side_effect=RuntimeError("boom"),
    ):
        payload = read_automation_settings()

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_automation_write_settings_returns_failure_when_update_fails():
    fake_db = Mock()
    payload = AutomationSettingsUpdate(
        enabled=True,
        locked=False,
        emergencyStop=False,
        allowedSymbols=["BTCUSDT"],
        maxRiskPerTrade=1.0,
        dailyLossLimit=4.0,
        maxOpenTrades=2,
        maxLeverage=3,
        maxPositionSize=1000.0,
        minConfidence=70.0,
        direction="BOTH",
    )

    with patch("app.api.v1.automation_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.automation_api.update_automation_settings",
        side_effect=RuntimeError("boom"),
    ):
        result = write_automation_settings(payload)

    assert result["status"] == "FAILED"
    assert result["changed"] is False
    assert result["settings"] is None
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_orderflow_returns_failure_when_payload_build_fails():
    fake_db = Mock()

    with patch("app.api.v1.orderflow_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.orderflow_api.build_orderflow_payload",
        side_effect=RuntimeError("boom"),
    ):
        payload = get_orderflow("BNBUSDT")

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_regime_catalog_returns_failure_when_catalog_build_fails():
    with patch("app.api.v1.regime_api.regime_catalog", side_effect=RuntimeError("boom")):
        payload = get_regime_catalog()

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"


def test_regime_catalog_exposes_governed_contract():
    payload = get_regime_catalog()

    assert payload["regime_contract"]["version"] == "v3_regime_13_v2"
    assert payload["regime_contract"]["thresholds"]["min_transition_confidence"] == 62
    assert payload["regime_contract"]["count"] == 13


def test_regime_summary_returns_failure_when_query_fails():
    fake_db = Mock()

    with patch("app.api.v1.regime_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.regime_api._load_regime_records",
        side_effect=RuntimeError("boom"),
    ):
        payload = get_regime_summary("BNBUSDT")

    assert payload["status"] == "FAILED"
    assert payload["count"] == 0
    assert payload["regime_counts"] == {}
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_risk_bundle_returns_failure_when_signal_build_fails():
    fake_db = Mock()

    with patch("app.api.v1.risk_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.risk_api.build_signal_payload",
        side_effect=RuntimeError("boom"),
    ):
        payload = get_risk_bundle("BNBUSDT")

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert payload["risk"] is None
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_smc_returns_failure_when_payload_build_fails():
    fake_db = Mock()

    with patch("app.api.v1.smc_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.smc_api.build_smc_payload",
        side_effect=RuntimeError("boom"),
    ):
        payload = get_smc("BNBUSDT")

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_symbols_list_returns_failure_when_repository_query_fails():
    fake_db = Mock()

    with patch("app.api.v1.symbols_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.symbols_api.SymbolRepository.get_active_symbols",
        side_effect=RuntimeError("boom"),
    ):
        payload = list_symbols()

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert payload["count"] == 0
    assert payload["records"] == []
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_symbols_seed_returns_failure_when_commit_fails():
    fake_db = Mock()
    fake_db.query.return_value.filter.return_value.first.return_value = None

    with patch("app.api.v1.symbols_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.symbols_api.commit_or_rollback",
        side_effect=RuntimeError("boom"),
    ):
        payload = seed_default_symbols()

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert payload["created"] == []
    assert payload["activated"] == []
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_thesis_routes_return_failure_when_query_fails():
    fake_db = Mock()

    with patch("app.api.v1.thesis_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.thesis_api.TradeThesisRepository.list_theses",
        side_effect=RuntimeError("boom"),
    ):
        payload = get_trade_theses("BNBUSDT")

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert payload["count"] == 0
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_latest_thesis_route_returns_failure_when_query_fails():
    fake_db = Mock()

    with patch("app.api.v1.thesis_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.thesis_api.TradeThesisRepository.latest_for_symbol",
        side_effect=RuntimeError("boom"),
    ):
        payload = get_latest_trade_thesis("BNBUSDT")

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert payload["latest"] is None
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_thesis_snapshot_as_of_route_returns_latest_snapshot():
    fake_db = Mock()
    snapshot = Mock()
    snapshot.id = 7
    snapshot.thesis_id = 3
    snapshot.thesis_key = "BTCUSDT:LONG:1"
    snapshot.symbol = "BTCUSDT"
    snapshot.side = "LONG"
    snapshot.lifecycle_state = "ACTIVE"
    snapshot.source_timestamp = datetime(2026, 6, 24, 3, 0, 0)
    snapshot.effective_timestamp = datetime(2026, 6, 24, 3, 0, 0)
    snapshot.snapshot_version = "thesis_snapshot_v1"
    snapshot.created_at = datetime(2026, 6, 24, 3, 0, 1)

    with patch("app.api.v1.thesis_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.thesis_api.get_thesis_snapshot_as_of",
        return_value=snapshot,
    ), patch(
        "app.api.v1.thesis_api.serialize_thesis_snapshot",
        return_value={"id": 7, "lifecycle_state": "ACTIVE"},
    ):
        payload = get_thesis_snapshot_as_of_route("BTCUSDT", as_of=datetime(2026, 6, 24, 3, 5, 0))

    assert payload["source"] == "thesis_snapshot"
    assert payload["latest"]["id"] == 7
    assert payload["leakage_diagnostics"]["status"] == "PASS"
    assert payload["leakage_diagnostics"]["thesis_snapshot"]["within_as_of"] is True
    assert fake_db.close.called


def test_trade_thesis_lineage_route_returns_latest_thesis_and_snapshot():
    fake_db = Mock()
    thesis = Mock()
    thesis.id = 3
    thesis.thesis_key = "BTCUSDT:LONG:1"
    thesis.symbol = "BTCUSDT"
    thesis.side = "LONG"
    thesis.title = "BTCUSDT LONG thesis"
    thesis.lifecycle_state = "ACTIVE"
    thesis.lifecycle_reason = None
    thesis.source_signal = "LONG"
    thesis.confidence = 82.0
    thesis.mode = "intraday"
    thesis.entry_timeframe = "1h"
    thesis.timeframe_stack = "5m,15m,1h"
    thesis.regime = "TRENDING_BULL"
    thesis.trade_plan_id = 1
    thesis.risk_decision_id = 7
    thesis.paper_trade_id = None
    thesis.assumptions_json = "{}"
    thesis.invalidation_json = "{}"
    thesis.targets_json = "{}"
    thesis.scenario_json = "{}"
    thesis.contradiction_json = "{}"
    thesis.created_at = datetime(2026, 6, 24, 3, 0, 0)
    thesis.updated_at = datetime(2026, 6, 24, 3, 5, 0)
    snapshot = Mock()
    snapshot.id = 8
    snapshot.thesis_id = 3
    snapshot.thesis_key = "BTCUSDT:LONG:1"
    snapshot.symbol = "BTCUSDT"
    snapshot.side = "LONG"
    snapshot.lifecycle_state = "ACTIVE"
    snapshot.source_timestamp = datetime(2026, 6, 24, 3, 5, 0)
    snapshot.effective_timestamp = datetime(2026, 6, 24, 3, 5, 0)
    snapshot.snapshot_version = "thesis_snapshot_v1"
    snapshot.created_at = datetime(2026, 6, 24, 3, 5, 1)

    with patch("app.api.v1.thesis_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.thesis_api.TradeThesisRepository.latest_for_symbol",
        return_value=thesis,
    ), patch(
        "app.api.v1.thesis_api.get_thesis_snapshot_as_of",
        return_value=snapshot,
    ), patch(
        "app.api.v1.thesis_api.serialize_thesis",
        return_value={"id": 3, "lifecycle_state": "ACTIVE"},
    ), patch(
        "app.api.v1.thesis_api.serialize_thesis_snapshot",
        return_value={"id": 8, "lifecycle_state": "ACTIVE"},
    ):
        payload = get_trade_thesis_lineage("BTCUSDT")

    assert payload["source"] == "trade_thesis_lineage"
    assert payload["latest"]["id"] == 3
    assert payload["latest_snapshot"]["id"] == 8
    assert payload["lifecycle_match"] is True
    assert payload["leakage_diagnostics"]["status"] == "PASS"
    assert fake_db.close.called


def test_trade_plan_returns_failure_when_query_fails():
    fake_db = Mock()
    fake_db.query.side_effect = RuntimeError("boom")

    with patch("app.api.v1.trade_plan_api.SessionLocal", return_value=fake_db):
        payload = get_trade_plan("BNBUSDT", status=None)

    assert payload["status"] == "FAILED"
    assert payload["error"] == "boom"
    assert payload["count"] == 0
    assert fake_db.rollback.called
    assert fake_db.close.called
