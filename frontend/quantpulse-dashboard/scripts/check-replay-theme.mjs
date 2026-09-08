// Local, synthetic UI regression. No production requests or paper orders.
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { createServer } from "vite";

const server = await createServer({ server: { port: 5178, open: false, hmr: false } });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  page.on("console", (message) => { if (message.type() === "error") console.error(message.text()); });
  const errors = [], periods = [];
  page.on("pageerror", (error) => { errors.push(error.message); console.error(error.message); });
  await page.route("**/backtest/**", async (route) => {
    const request = route.request();
    periods.push(request.postData() || request.url());
    await route.fulfill({ json: { status: "COMPLETED", response: {
      start: "2026-09-01", end: "2026-09-08", price_bars: 2015,
      price_coverage_percent: 99.95, venue: "BINANCE", initial_capital_inr: 200000,
      notional_percent: 85, fee_bps_per_side: 7.5, last_price_at: "2026-09-08T10:00:00Z",
      limitations: ["Synthetic theme regression fixture, not actual performance."],
      results: [{ strategy_id: "CORE_SIGNAL", name: "Core Signal", version: "core_signal_v1",
        status: "REPLAYED", decisions: 100, eligible_decisions: 20, closed_trades: 11,
        open_positions: 0, win_rate: 50, pnl_inr: 120, target1_hits: 6, target2_exits: 3,
        stop_exits: 5, profit_factor: 1.2, realized_drawdown_percent: 2, censored_positions: 0,
        skipped: { MISSING_EVIDENCE: 2 }, trades: Array.from({length: 11}, (_, index) => ({
          opened_at: `2026-09-0${index % 8 + 1}T10:00:00Z`, closed_at: "2026-09-08T11:00:00Z",
          side: "LONG", timeframe: "1h", entry: 100, exit: 101, reason: "TARGET2", pnl_inr: 10,
        })) }],
    } }, headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:5178", "Access-Control-Allow-Credentials": "true" } });
  });
  await page.route("**/__replay-theme", (route) => route.fulfill({ contentType: "text/html", body: `
    <!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
    <body><main class="qp-main" style="padding:20px"><div id="test-root"></div></main>
    <script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$ = () => {};
      window.$RefreshSig$ = () => (type) => type;
      window.__vite_plugin_react_preamble_installed__ = true;
      await import('/src/styles.css');
      const reactModule = await import('/node_modules/.vite/deps/react.js');
      const React = reactModule.default || reactModule;
      const rootModule = await import('/node_modules/.vite/deps/react-dom_client.js');
      const {createRoot} = rootModule.default || rootModule;
      const {default: Comparison} = await import('/src/components/StrategyBacktestComparison.jsx');
      createRoot(document.getElementById('test-root')).render(React.createElement(Comparison, {symbol:'BTCUSDT'}));
    </script></body></html>` }));
  await page.goto("http://127.0.0.1:5178/__replay-theme");
  await page.getByRole("button", { name: "Core Signal", exact: true }).waitFor({timeout: 15000}).catch(async (error) => {
    console.error(await page.locator("body").innerText());
    throw error;
  });
  const colors = await page.locator(".qp-replay-panel").evaluate((panel) => {
    const style = (element) => { const css = getComputedStyle(element); return [css.backgroundColor, css.color]; };
    return { panel: style(panel), select: style(panel.querySelector("select")),
      muted: style(panel.querySelector(".text-slate-600")), header: style(panel.querySelector("th")),
      link: style(panel.querySelector(".text-blue-700")), warning: style(panel.querySelector(".text-amber-700")) };
  });
  assert.deepEqual(colors.panel, ["rgb(255, 255, 255)", "rgb(16, 33, 58)"]);
  assert.deepEqual(colors.select, colors.panel);
  assert.deepEqual(colors.header, ["rgb(246, 248, 251)", "rgb(64, 81, 106)"]);
  assert.equal(colors.muted[1], "rgb(82, 100, 122)");
  assert.equal(colors.link[1], "rgb(29, 78, 216)");
  assert.equal(colors.warning[1], "rgb(146, 64, 14)");
  await page.getByRole("button", {name: "Next", exact: true}).click();
  await page.getByText("Page 2 of 2", {exact: true}).waitFor();
  await page.getByRole("combobox").selectOption("14");
  await page.getByText("Page 1 of 2", {exact: true}).waitFor();
  assert(periods.some((value) => value.includes('14')));
  await page.screenshot({path: "../../artifacts/replay-light-desktop.png", fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  assert(await page.locator(".qp-replay-panel").evaluate((panel) => panel.getBoundingClientRect().right <= innerWidth));
  await page.screenshot({path: "../../artifacts/replay-light-mobile.png", fullPage: true});
  assert.deepEqual(errors, []);
  console.log("PASS: light surfaces, readable text/control colors, pagination, automatic period reload, mobile containment");
} finally {
  await browser?.close();
  await server.close();
}
