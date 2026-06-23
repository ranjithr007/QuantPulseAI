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
        dashboard_api = (FRONTEND_ROOT / "src" / "hooks" / "dashboardApi.js").read_text(
            encoding="utf-8"
        )
        header = (FRONTEND_ROOT / "src" / "components" / "DashboardHeader.jsx").read_text(
            encoding="utf-8"
        )

        self.assertEqual(package_json["name"], "quantpulse-dashboard")
        self.assertIn("react", package_json["dependencies"])
        self.assertIn("react-dom", package_json["dependencies"])
        self.assertIn("vite", package_json["devDependencies"])
        self.assertIn("@vitejs/plugin-react", package_json["devDependencies"])
        self.assertEqual(package_json["scripts"]["dev"], "vite")
        self.assertEqual(package_json["scripts"]["build"], "vite build")
        self.assertIn("react()", vite_config)
        self.assertIn("tailwindcss()", vite_config)
        self.assertIn("createRoot", source)
        self.assertIn("<Routes>", source)
        self.assertIn("VITE_BACKEND_URL", dashboard_api)
        self.assertIn('"/signals/watchlist"', dashboard_api)
        self.assertIn('"/paper-trade/bundle"', dashboard_api)
        self.assertIn('"/pipeline/status"', dashboard_api)
        self.assertIn("QuantPulseAI", header)
        self.assertIn('label: "Signals"', header)
        self.assertIn('label: "Backtest"', header)

    def test_frontend_styles_support_dashboard_layout(self):
        styles = (FRONTEND_ROOT / "src" / "styles.css").read_text(encoding="utf-8")
        dashboard = (FRONTEND_ROOT / "src" / "pages" / "DashboardHomePage.jsx").read_text(
            encoding="utf-8"
        )
        signal_table = (
            FRONTEND_ROOT / "src" / "components" / "MarketSignalTable.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn('@import "tailwindcss"', styles)
        self.assertIn("--panel", styles)
        self.assertIn("market-tape-track", styles)
        self.assertIn("xl:grid-cols", dashboard)
        self.assertIn("overflow-x-auto", signal_table)
        self.assertIn("<table", signal_table)


if __name__ == "__main__":
    unittest.main()
