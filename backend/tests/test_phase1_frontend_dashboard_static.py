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

    def test_pnl_page_shows_the_account_wide_trade_ledger_without_row_caps(self):
        dashboard_api = (FRONTEND_ROOT / "src" / "hooks" / "dashboardApi.js").read_text(
            encoding="utf-8"
        )
        pnl_section = (
            FRONTEND_ROOT / "src" / "components" / "PnLSection.jsx"
        ).read_text(encoding="utf-8")

        scoped_pages = dashboard_api.split(
            "const SYMBOL_SCOPED_PAPER_PAGES = new Set([", 1
        )[1].split("]);", 1)[0]

        self.assertNotIn('"pnl"', scoped_pages)
        self.assertIn('include_all: activePage === "pnl" ? true : null', dashboard_api)
        self.assertIn("openPositions.map((trade)", pnl_section)
        self.assertIn("tradeHistory.map((trade)", pnl_section)
        self.assertNotIn("openPositions.slice(", pnl_section)
        self.assertNotIn("tradeHistory.slice(", pnl_section)
        self.assertIn("Stop-loss", pnl_section)
        self.assertIn("Target 1", pnl_section)
        self.assertIn("Target 2", pnl_section)
        self.assertIn("remainingPositionLabel(trade)", pnl_section)
        self.assertIn("exitDeadlineLabel(trade)", pnl_section)
        self.assertIn('"PAPER_STAGED_EXIT_V1"', pnl_section)
        self.assertIn('"BTC_1H_STAGED_V1"', pnl_section)
        self.assertIn('rawRemaining === null', pnl_section)
        self.assertIn('0.75% SL / 1.5% T1 / 2.3% T2', pnl_section)


if __name__ == "__main__":
    unittest.main()
