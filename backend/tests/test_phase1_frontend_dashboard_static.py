import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend" / "quantpulse-dashboard"


class Phase1FrontendDashboardStaticTests(unittest.TestCase):
    def test_frontend_scaffold_is_react_based(self):
        package_json = json.loads((FRONTEND_ROOT / "package.json").read_text(encoding="utf-8"))
        vite_config = (FRONTEND_ROOT / "vite.config.js").read_text(encoding="utf-8")
        source = (FRONTEND_ROOT / "src" / "main.jsx").read_text(encoding="utf-8")

        self.assertEqual(package_json["name"], "quantpulse-dashboard")
        self.assertIn("react", package_json["dependencies"])
        self.assertIn("react-dom", package_json["dependencies"])
        self.assertIn("vite", package_json["devDependencies"])
        self.assertIn("@vitejs/plugin-react", package_json["devDependencies"])
        self.assertEqual(package_json["scripts"]["dev"], "vite")
        self.assertEqual(package_json["scripts"]["build"], "vite build")
        self.assertIn("react()", vite_config)
        self.assertIn('/signals', vite_config)
        self.assertIn('/paper-trade', vite_config)
        self.assertIn('/pipeline', vite_config)
        self.assertIn("createRoot", source)
        self.assertIn("requestJson(`/signals/${state.symbol}`", source)
        self.assertIn("requestJson(`/signals/watchlist`", source)
        self.assertIn("requestJson(`/paper-trade/performance`", source)
        self.assertIn("requestJson(`/pipeline/status`", source)
        self.assertIn("QuantPulseAI", source)
        self.assertIn("Watchlist", source)
        self.assertIn("Pipeline", source)

    def test_frontend_styles_support_dashboard_layout(self):
        styles = (FRONTEND_ROOT / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("--panel", styles)
        self.assertIn(".metric-grid", styles)
        self.assertIn(".two-col", styles)
        self.assertIn(".three-col", styles)
        self.assertIn(".table-wrap", styles)
        self.assertIn(".stack-cards", styles)


if __name__ == "__main__":
    unittest.main()
