import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.automation_settings import AutomationSetting
from app.database.models.automation_settings import AutomationSettingsAudit
from app.repositories.automation_settings_repository import automation_settings_payload
from app.repositories.automation_settings_repository import get_automation_settings
from app.repositories.automation_settings_repository import list_automation_audit
from app.repositories.automation_settings_repository import normalize_automation_settings
from app.repositories.automation_settings_repository import set_emergency_stop
from app.repositories.automation_settings_repository import update_automation_settings


class AutomationSettingsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        AutomationSetting.__table__.create(engine)
        AutomationSettingsAudit.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)

    def test_default_policy_is_locked_and_paper_only(self):
        with self.Session() as db:
            settings = automation_settings_payload(get_automation_settings(db))

            self.assertFalse(settings["enabled"])
            self.assertTrue(settings["locked"])
            self.assertEqual("PAPER", settings["executionMode"])
            self.assertFalse(settings["liveExecutionEnabled"])
            self.assertFalse(settings["governance"]["promotion_enabled"])
            self.assertFalse(settings["governance"]["ml_authority_enabled"])
            self.assertEqual(40.0, settings["minConfidence"])
            self.assertEqual(4.0, settings["dailyLossLimit"])
            self.assertEqual(4, settings["maxOpenTrades"])
            self.assertFalse(settings["maxRiskPerTradeEnabled"])
            self.assertFalse(settings["dailyLossLimitEnabled"])
            self.assertFalse(settings["maxOpenTradesEnabled"])
            self.assertEqual(
                40.0,
                settings["governance"]["min_entry_confidence"],
            )
            self.assertEqual(
                60.0,
                settings["governance"]["full_size_entry_confidence"],
            )
            self.assertEqual(
                0.5,
                settings["governance"]["minimum_tier_risk_percent"],
            )
            self.assertEqual(
                ["1h", "2h", "4h", "1d"],
                settings["governance"]["official_entry_timeframes"],
            )
            self.assertEqual(1, settings["version"])

    def test_settings_update_is_persisted_and_audited(self):
        with self.Session() as db:
            get_automation_settings(db)
            settings, changed = update_automation_settings(
                db,
                {"enabled": True, "locked": False, "allowedSymbols": ["BTCUSDT"]},
                actor="unit_test",
            )

            self.assertTrue(changed)
            self.assertTrue(settings["enabled"])
            self.assertFalse(settings["locked"])
            self.assertEqual(["BTCUSDT"], settings["allowedSymbols"])
            self.assertEqual(2, settings["version"])
            audit = list_automation_audit(db)
            self.assertEqual("SETTINGS_UPDATED", audit[0]["action"])
            self.assertEqual("unit_test", audit[0]["actor"])
            self.assertIn("enabled", audit[0]["changedFields"])

    def test_legacy_or_requested_confidence_cannot_override_governed_40_boundary(self):
        with self.Session() as db:
            row = get_automation_settings(db)
            row.min_confidence = 70
            db.commit()

            self.assertEqual(40.0, automation_settings_payload(row)["minConfidence"])
            settings, _ = update_automation_settings(
                db,
                {"minConfidence": 60},
                actor="unit_test",
            )
            self.assertEqual(40.0, settings["minConfidence"])
            self.assertEqual(40.0, row.min_confidence)

    def test_emergency_stop_forces_disabled_and_locked(self):
        with self.Session() as db:
            get_automation_settings(db)
            update_automation_settings(db, {"enabled": True, "locked": False})

            settings, changed = set_emergency_stop(db, True, actor="unit_test")

            self.assertTrue(changed)
            self.assertTrue(settings["emergencyStop"])
            self.assertFalse(settings["enabled"])
            self.assertTrue(settings["locked"])
            self.assertEqual("EMERGENCY_STOP_ACTIVATED", list_automation_audit(db)[0]["action"])

    def test_legacy_unsafe_account_limits_are_repaired_and_audited(self):
        with self.Session() as db:
            row = get_automation_settings(db)
            row.daily_loss_limit = 15
            row.max_open_trades = 20
            db.commit()

            repaired = automation_settings_payload(get_automation_settings(db))

            self.assertEqual(4.0, repaired["dailyLossLimit"])
            self.assertEqual(4, repaired["maxOpenTrades"])
            self.assertEqual(4.0, row.daily_loss_limit)
            self.assertEqual(4, row.max_open_trades)
            audit = list_automation_audit(db)[0]
            self.assertEqual("GOVERNED_PAPER_SETTINGS_REPAIRED", audit["action"])
            self.assertIn("dailyLossLimit", audit["changedFields"])
            self.assertIn("maxOpenTrades", audit["changedFields"])

    def test_requested_account_limits_are_clamped_to_safe_ceiling(self):
        normalized = normalize_automation_settings(
            {"dailyLossLimit": 15, "maxOpenTrades": 20}
        )

        self.assertEqual(4.0, normalized["dailyLossLimit"])
        self.assertEqual(4, normalized["maxOpenTrades"])


if __name__ == "__main__":
    unittest.main()
