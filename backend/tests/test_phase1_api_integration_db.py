import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["QUANTPULSE_START_SCHEDULER"] = "false"

TEST_DB_PATH = Path(tempfile.gettempdir()) / "quantpulse_api_integration.sqlite"
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_PATH.as_posix()}"
TEST_ENGINE = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)

from app.config import get_settings
from app.database.models.automation_settings import AutomationSetting
from app.database.models.automation_settings import AutomationSettingsAudit
from app.database.models.paper_trade import PaperTrade
from app.database.models.risk_decision import RiskDecision
from app.database.models.trade_plan import TradePlan
from app.database.sqlserver import Base
from app.api.v1 import paper_trade_api
from app.main import app
from app.repositories.automation_settings_repository import update_automation_settings
from app.trading.trade_plan_engine import build_trade_plan


class Phase1ApiIntegrationDbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_settings.cache_clear()
        cls._original_session_local = paper_trade_api.SessionLocal
        paper_trade_api.SessionLocal = TestSessionLocal
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        paper_trade_api.SessionLocal = cls._original_session_local
        cls.client.close()
        TEST_ENGINE.dispose()
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()

    def setUp(self):
        AutomationSettingsAudit.__table__.drop(bind=TEST_ENGINE, checkfirst=True)
        AutomationSetting.__table__.drop(bind=TEST_ENGINE, checkfirst=True)
        PaperTrade.__table__.drop(bind=TEST_ENGINE, checkfirst=True)
        RiskDecision.__table__.drop(bind=TEST_ENGINE, checkfirst=True)
        TradePlan.__table__.drop(bind=TEST_ENGINE, checkfirst=True)

        TradePlan.__table__.create(bind=TEST_ENGINE, checkfirst=True)
        RiskDecision.__table__.create(bind=TEST_ENGINE, checkfirst=True)
        PaperTrade.__table__.create(bind=TEST_ENGINE, checkfirst=True)
        AutomationSetting.__table__.create(bind=TEST_ENGINE, checkfirst=True)
        AutomationSettingsAudit.__table__.create(bind=TEST_ENGINE, checkfirst=True)

        with TestSessionLocal() as db:
            update_automation_settings(
                db,
                {"enabled": True, "locked": False},
                actor="integration_test",
            )
            trade_created_at = datetime.utcnow() - timedelta(minutes=2)
            risk_created_at = datetime.utcnow() - timedelta(minutes=1)
            governed = build_trade_plan("LONG", 100.0, 1.0, confidence=50)

            trade = TradePlan(
                symbol="BTCUSDT",
                side="LONG",
                entry_price=100.0,
                stop_loss=governed["stop_loss"],
                target1=governed["target1"],
                target2=governed["target2"],
                target3=governed["target3"],
                risk_reward=governed["risk_reward"],
                confidence=50.0,
                entry_timeframe="1h",
                status="OPEN",
                created_at=trade_created_at,
            )
            db.add(trade)
            db.flush()

            risk = RiskDecision(
                symbol="BTCUSDT",
                signal="LONG",
                decision="APPROVE",
                entry_price=100.0,
                stop_loss=governed["stop_loss"],
                target1=governed["target1"],
                target2=governed["target2"],
                risk_reward=governed["risk_reward"],
                position_size=1.0,
                risk_percent=1.0,
                confidence=50.0,
                created_at=risk_created_at,
            )
            db.add(risk)
            db.commit()

    def test_paper_trade_candidate_execution_uses_test_database(self):
        candidates = self.client.get("/paper-trade/candidates?symbol=BTCUSDT")
        self.assertEqual(candidates.status_code, 200)

        payload = candidates.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["eligible_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertTrue(payload["records"][0]["eligible"])
        self.assertEqual(payload["records"][0]["fill_profile"]["entry_fill_price"], 100.14)

        executed = self.client.post("/paper-trade/execute-candidates?symbol=BTCUSDT")
        self.assertEqual(executed.status_code, 200)

        execution = executed.json()
        self.assertEqual(execution["candidate_count"], 1)
        self.assertEqual(execution["executed_count"], 1)
        self.assertEqual(execution["skipped_count"], 0)
        self.assertEqual(execution["executed"][0]["status"], "OPEN")
        self.assertEqual(execution["executed"][0]["fill_profile"]["entry_fill_price"], 100.14)
        self.assertEqual(execution["executed"][0]["entry_price"], 100.14)

        open_trades = self.client.get("/paper-trade/trades?status=OPEN&symbol=BTCUSDT")
        self.assertEqual(open_trades.status_code, 200)

        open_payload = open_trades.json()
        self.assertEqual(open_payload["count"], 1)
        self.assertEqual(open_payload["summary"]["open"], 1)
        self.assertEqual(open_payload["summary"]["closed"], 0)
        self.assertEqual(open_payload["records"][0]["entry_price"], 100.14)

        performance = self.client.get("/paper-trade/performance?symbol=BTCUSDT")
        self.assertEqual(performance.status_code, 200)

        perf_payload = performance.json()["performance"]
        self.assertEqual(perf_payload["total_trades"], 1)
        self.assertEqual(perf_payload["open_trades"], 1)
        self.assertEqual(perf_payload["closed_trades"], 0)
        self.assertEqual(perf_payload["win_rate"], 0)

    def test_fill_model_endpoint_returns_simulation_profile(self):
        response = self.client.get(
            "/paper-trade/fill-model",
            params={
                "side": "LONG",
                "planned_entry_price": 100,
                "stop_loss": 99,
                "target1": 102,
                "confidence": 50,
                "risk_reward": 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "paper_trade_fill_model")
        self.assertEqual(payload["profile"]["entry_fill_price"], 100.06)
        self.assertEqual(payload["profile"]["fill_quality"], "NORMAL")


if __name__ == "__main__":
    unittest.main()
