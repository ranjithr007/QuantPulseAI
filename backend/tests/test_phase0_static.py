import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase0StaticSmokeTests(unittest.TestCase):
    def test_backend_python_files_parse(self):
        errors = []

        for path in APP_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                ast.parse(path.read_text(encoding="utf-8-sig"))
            except SyntaxError as exc:
                errors.append(f"{path}: {exc}")

        self.assertEqual(errors, [])

    def test_main_wires_phase0_routers(self):
        main_text = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        expected_routers = [
            "health_api.router",
            "features_api.router",
            "orderflow_api.router",
            "smc_api.router",
            "master_ai_v2_api.router",
            "fusion_ai_api.router",
            "backtest_api.router",
            "ml_api.router",
            "dataset_api.router",
            "ml_label_api.router",
            "prediction_api.router",
            "risk_api.router",
            "signals_api.router",
            "paper_trade_api.router",
            "pipeline_api.router",
        ]

        for router in expected_routers:
            with self.subTest(router=router):
                self.assertIn(router, main_text)

    def test_runtime_config_is_environment_driven(self):
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        database_runtime_text = (APP_ROOT / "database" / "runtime.py").read_text(encoding="utf-8")

        self.assertIn("QUANTPULSE_DATABASE_URL", config_text)
        self.assertIn("QUANTPULSE_START_SCHEDULER", config_text)
        self.assertIn("QUANTPULSE_SQL_ENCRYPT", config_text)
        self.assertIn("QUANTPULSE_SQL_TRUST_SERVER_CERTIFICATE", config_text)
        self.assertIn("Encrypt", config_text)
        self.assertIn("TrustServerCertificate", config_text)
        self.assertIn("get_settings().database_url", database_runtime_text)


if __name__ == "__main__":
    unittest.main()
