// Run with Vite on port 5173: node scripts/check-strategy-comparison.mjs
// Only synthetic responses; never connects to the deployed API or places orders.
import assert from "node:assert/strict";
import { chromium } from "playwright-core";

const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => { errors.push(error.message); console.error(error.message); });
  page.on("console", (message) => { if (message.type() === "error") console.error(message.text()); });
  const submissions = [];
  const report = {
    symbol: "ETHUSDT", start: "2026-09-01T00:00:00Z", end: "2026-09-02T00:00:00Z",
    initial_capital_inr: 200000, notional_percent: 85, fee_bps_per_side: 15,
    price_bars: 288, price_coverage_percent: 100, venue: "BINANCE", limitations: ["Synthetic browser test"],
    results: [{ strategy_id: "CORE_SIGNAL", version: "v1", name: "Core Signal", status: "REPLAYED",
      closed_trades: 12, open_positions: 0, decisions: 30, eligible_decisions: 15, win_rate: 50,
      pnl_inr: 200, target1_hits: 6, target2_exits: 6, stop_exits: 6, profit_factor: 1.2,
      realized_drawdown_percent: 1, censored_positions: 0, excluded_decisions: 0,
      trades: Array.from({ length: 12 }, (_, index) => ({ opened_at: `2026-09-01T${String(index).padStart(2, "0")}:00:00Z`,
        closed_at: "2026-09-02T00:00:00Z", side: "LONG", timeframe: "1h", entry: 100, exit: 102, reason: "TARGET2", pnl_inr: 20 })),
    }],
  };
  await page.route("**/backtest/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("strategy-comparison/jobs")) {
      submissions.push(Object.fromEntries(url.searchParams));
      await route.fulfill({ json: { status: "QUEUED", job_id: "test-job" }, headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:5173", "Access-Control-Allow-Credentials": "true" } });
    } else {
      await route.fulfill({ json: { status: "COMPLETED", job_id: "test-job", response: report }, headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:5173", "Access-Control-Allow-Credentials": "true" } });
    }
  });
  await page.route("**/__strategy-test", (route) => route.fulfill({ contentType: "text/html", body: `<!doctype html><div id="test-root"></div>
    <script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$ = () => {};
      window.$RefreshSig$ = () => (type) => type;
      window.__vite_plugin_react_preamble_installed__ = true;
      const reactModule = await import('/node_modules/.vite/deps/react.js');
      const React = reactModule.default || reactModule;
      const rootModule = await import('/node_modules/.vite/deps/react-dom_client.js');
      const {createRoot} = rootModule.default || rootModule;
      const {default: Comparison} = await import('/src/components/StrategyBacktestComparison.jsx');
      createRoot(document.getElementById('test-root')).render(React.createElement(Comparison, {symbol:'ETHUSDT'}));
    </script>` }));
  await page.goto("http://127.0.0.1:5173/__strategy-test");
  await page.getByRole("button", { name: "Core Signal", exact: true }).waitFor({ timeout: 20000 });
  assert.equal(submissions[0].symbol, "ETHUSDT");
  assert.equal(submissions[0].days, "7");
  await page.getByRole("button", { name: "Core Signal", exact: true }).click();
  assert.equal(await page.getByText("Page 1 of 2").count(), 1);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  assert.equal(await page.getByText("Page 2 of 2").count(), 1);
  await page.getByLabel("Strategy replay period").selectOption("14");
  await page.getByRole("button", { name: "Core Signal", exact: true }).waitFor({ timeout: 20000 });
  assert.equal(submissions.at(-1).days, "14");
  assert.equal(await page.getByText("Page 2 of 2").count(), 0);
  assert.deepEqual(errors, []);
  console.log("PASS: automatic queue/poll, report rendering, pagination and period reset");
} finally {
  await browser.close();
}
