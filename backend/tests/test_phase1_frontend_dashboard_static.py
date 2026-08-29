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
        trading_view = (
            FRONTEND_ROOT
            / "src"
            / "components"
            / "signal-details"
            / "AdvancedTradingViewPanel.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn('@import "tailwindcss"', styles)
        self.assertIn("--panel", styles)
        self.assertIn("color-scheme: light", styles)
        self.assertIn("--color-slate-950: #f4f7fb", styles)
        self.assertIn("--color-slate-900: #ffffff", styles)
        self.assertIn(".qp-sidebar", styles)
        self.assertIn(".qp-topbar", styles)
        self.assertIn(".qp-metric-card", styles)
        self.assertIn(".qp-auth-shell", styles)
        self.assertIn("--scrollbar-thumb", styles)
        self.assertIn("*::-webkit-scrollbar-thumb:hover", styles)
        self.assertIn(".qp-sidebar nav::-webkit-scrollbar-thumb", styles)
        self.assertIn("main .overflow-x-auto::-webkit-scrollbar", styles)
        self.assertIn("scrollbar-width: none !important", styles)
        self.assertIn("market-tape-viewport", styles)
        self.assertNotIn("market-tape-track", styles)
        self.assertIn('theme: "light"', trading_view)
        self.assertIn('backgroundColor: "rgba(255, 255, 255, 1)"', trading_view)
        self.assertIn("xl:grid-cols", dashboard)
        self.assertIn("overflow-x-auto", signal_table)
        self.assertIn("<table", signal_table)
        self.assertIn("Spot confirm", signal_table)
        self.assertIn("selectWatchlistSignal", signal_table)
        self.assertIn("watchRow.entry_timeframe", signal_table)

    def test_market_and_signals_pages_have_distinct_responsibilities(self):
        dashboard_api = (FRONTEND_ROOT / "src" / "hooks" / "dashboardApi.js").read_text(
            encoding="utf-8"
        )
        market = (
            FRONTEND_ROOT / "src" / "components" / "LiveMarketSection.jsx"
        ).read_text(encoding="utf-8")
        signals = (
            FRONTEND_ROOT / "src" / "components" / "SignalScannerSection.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn("Market scan table", market)
        self.assertIn("<MarketSignalTable", market)
        self.assertIn("Actionable signals", signals)
        self.assertIn('row.type === "BUY" || row.type === "SELL"', signals)
        self.assertIn("WAIT coins remain in the Market overview", signals)
        self.assertNotIn("<MarketSignalTable", signals)
        self.assertIn('activePage !== "signals"', dashboard_api)

    def test_market_move_page_combines_live_engines_without_fake_macro_data(self):
        main = (FRONTEND_ROOT / "src" / "main.jsx").read_text(encoding="utf-8")
        header = (
            FRONTEND_ROOT / "src" / "components" / "DashboardHeader.jsx"
        ).read_text(encoding="utf-8")
        dashboard_api = (
            FRONTEND_ROOT / "src" / "hooks" / "dashboardApi.js"
        ).read_text(encoding="utf-8")
        dashboard_data = (
            FRONTEND_ROOT / "src" / "hooks" / "useDashboardData.jsx"
        ).read_text(encoding="utf-8")
        market_move = (
            FRONTEND_ROOT / "src" / "pages" / "MarketMovePage.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn('path="/market-move"', main)
        self.assertIn('label: "Market Move"', header)
        self.assertIn('"market-move": { signals: true }', dashboard_api)
        self.assertIn('"market-move",', dashboard_data)
        for label in ("Macro", "Liquidations", "Order Flow", "Whales", "SMC", "Regime"):
            self.assertIn(f'label: "{label}"', market_move)
        self.assertIn("Continuation", market_move)
        self.assertIn("Pullback", market_move)
        self.assertIn("Reversal", market_move)
        self.assertIn("Next resistance", market_move)
        self.assertIn("Major support", market_move)
        self.assertIn('macroContext.status === "VERIFIED"', market_move)
        self.assertIn("news or Treasury drivers are never inferred or fabricated", market_move)

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
        self.assertIn("visibleTrades.map((trade)", pnl_section)
        self.assertNotIn("openPositions.slice(", pnl_section)
        self.assertIn("tradeHistory.slice(pageStart", pnl_section)
        self.assertIn("Trade history pagination", pnl_section)
        self.assertIn("Stop-loss", pnl_section)
        self.assertIn("Target 1", pnl_section)
        self.assertIn("Target 2", pnl_section)
        self.assertIn("remainingPositionLabel(trade)", pnl_section)
        self.assertIn("exitDeadlineLabel(trade)", pnl_section)
        self.assertIn('"PAPER_STAGED_EXIT_V2"', pnl_section)
        self.assertIn('"PAPER_ATR_STRUCTURE_V1"', pnl_section)
        self.assertIn('"BTC_1H_STAGED_V1"', pnl_section)
        self.assertIn('rawRemaining === null', pnl_section)
        self.assertIn("QA evidence quarantined", pnl_section)
        self.assertIn("ledgerScope.quarantined_records", pnl_section)
        self.assertIn('T1 closes 75% / protected stop / T2 closes 25%', pnl_section)
        self.assertIn("Deadline (IST)", pnl_section)
        self.assertIn("Closed (IST)", pnl_section)

        formatters = (
            FRONTEND_ROOT / "src" / "utils" / "formatters.js"
        ).read_text(encoding="utf-8")
        self.assertIn('const IST_TIME_ZONE = "Asia/Kolkata"', formatters)
        self.assertIn('`${raw}Z`', formatters)
        self.assertIn(')} IST`', formatters)
        self.assertIn('background: "#ffffff"', formatters)

    def test_risk_views_scope_open_trade_counts_and_charts_have_initial_size(self):
        auto_page = (
            FRONTEND_ROOT / "src" / "pages" / "AutoTradingPage.jsx"
        ).read_text(encoding="utf-8")
        risk_page = (
            FRONTEND_ROOT / "src" / "pages" / "RiskControlsPage.jsx"
        ).read_text(encoding="utf-8")
        rotation_page = (
            FRONTEND_ROOT / "src" / "pages" / "RotationPage.jsx"
        ).read_text(encoding="utf-8")

        for source in (auto_page, risk_page):
            self.assertIn('label="Selected coin trades"', source)
            self.assertIn("one active trade per coin", source)

        self.assertEqual(rotation_page.count("initialDimension="), 2)
        self.assertEqual(rotation_page.count("minWidth={0}"), 2)
        self.assertEqual(rotation_page.count("minHeight={0}"), 2)

    def test_redundant_views_and_repeated_rows_are_removed(self):
        main = (FRONTEND_ROOT / "src" / "main.jsx").read_text(encoding="utf-8")
        header = (
            FRONTEND_ROOT / "src" / "components" / "DashboardHeader.jsx"
        ).read_text(encoding="utf-8")
        dashboard_api = (
            FRONTEND_ROOT / "src" / "hooks" / "dashboardApi.js"
        ).read_text(encoding="utf-8")
        dashboard_data = (
            FRONTEND_ROOT / "src" / "hooks" / "useDashboardData.jsx"
        ).read_text(encoding="utf-8")
        backtest = (
            FRONTEND_ROOT / "src" / "pages" / "BacktestPage.jsx"
        ).read_text(encoding="utf-8")
        rotation = (
            FRONTEND_ROOT / "src" / "pages" / "RotationPage.jsx"
        ).read_text(encoding="utf-8")

        self.assertNotIn('label: "Trading Details"', header)
        self.assertIn('path="/trading-details"', main)
        self.assertIn('<Navigate to={buildPageUrl("auto-trading", view)} replace />', main)
        self.assertIn('backtest: { signals: true }', dashboard_api)
        self.assertIn("Paper-trading PNL is intentionally excluded", backtest)
        self.assertNotIn("paperTradeHistory", backtest)
        self.assertNotIn("[0, 1]", header)
        self.assertNotIn('dataKey="rsScore"', rotation)
        self.assertIn('dataKey="confidence"', rotation)
        self.assertIn("currentTimeframe", dashboard_data)
        self.assertIn("currentMode", dashboard_data)
        self.assertIn("const seenIds = new Set()", dashboard_data)
        self.assertIn('.startsWith("QA")', dashboard_data)

    def test_dashboard_layout_receives_paper_wallet_before_rendering_pnl_routes(self):
        source = (FRONTEND_ROOT / "src" / "main.jsx").read_text(encoding="utf-8")
        dashboard_call_start = source.index("<DashboardLayout")
        dashboard_call = source[
            dashboard_call_start : source.index("/>", dashboard_call_start)
        ]
        dashboard_signature_start = source.index("function DashboardLayout({")
        dashboard_signature = source[
            dashboard_signature_start : source.index(
                "}) {",
                dashboard_signature_start,
            )
        ]

        self.assertIn("paperWallet={paperWallet}", dashboard_call)
        self.assertIn("paperWallet,", dashboard_signature)

    def test_risk_controls_expose_only_governed_account_limit_ranges(self):
        main = (FRONTEND_ROOT / "src" / "main.jsx").read_text(encoding="utf-8")
        auto_trading = (
            FRONTEND_ROOT / "src" / "pages" / "AutoTradingPage.jsx"
        ).read_text(encoding="utf-8")
        automation = (
            FRONTEND_ROOT / "src" / "components" / "AutomationSection.jsx"
        ).read_text(encoding="utf-8")
        risk_controls = (
            FRONTEND_ROOT / "src" / "pages" / "RiskControlsPage.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn("Math.min(4, Number(value.dailyLossLimit)", main)
        self.assertIn("Math.min(4, Number(value.maxOpenTrades)", main)
        self.assertNotIn("max={15}", automation)
        self.assertNotIn("max={20}", automation)
        self.assertNotIn("max={15}", risk_controls)
        self.assertNotIn("max={20}", risk_controls)
        self.assertIn("Executor verdict", auto_trading)
        self.assertIn("<LifecyclePanel", auto_trading)
        self.assertNotIn("Executor verdict", risk_controls)
        self.assertNotIn("<LifecyclePanel", risk_controls)
        self.assertNotIn("Execution readiness", risk_controls)

    def test_live_refresh_uses_websocket_fallback_and_pauses_hidden_pages(self):
        dashboard_data = (
            FRONTEND_ROOT / "src" / "hooks" / "useDashboardData.jsx"
        ).read_text(encoding="utf-8")
        nginx = (FRONTEND_ROOT / "nginx.conf.template").read_text(encoding="utf-8")
        dockerfile = (FRONTEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("LIVE_SNAPSHOT_FALLBACK_MS = 30_000", dashboard_data)
        self.assertIn("LIVE_STATUS_FALLBACK_MS = 60_000", dashboard_data)
        self.assertIn("liveSocketConnected", dashboard_data)
        self.assertIn("pageVisible", dashboard_data)
        self.assertIn("if (!pageVisible) return undefined;", dashboard_data)
        self.assertNotIn("LIVE_SNAPSHOT_REFRESH_MS = 10_000", dashboard_data)
        self.assertIn("${QUANTPULSE_API_UPSTREAM}/ws/", nginx)
        self.assertIn("${QUANTPULSE_API_UPSTREAM}/;", nginx)
        self.assertIn("ENV QUANTPULSE_API_UPSTREAM=", dockerfile)


if __name__ == "__main__":
    unittest.main()
