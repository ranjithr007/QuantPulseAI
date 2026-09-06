// Synthetic local test only. Requires Vite on port 5173.
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const page = await browser.newPage();
  const errors = [], requests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/backtest/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const symbol = url.searchParams.get("symbol");
    let json = { records: [] };
    if (url.pathname.endsWith("/summary") && symbol === "SOLUSDT") {
      json = { records: [{ scope: { symbol, timeframe: "1h", signal: "SHORT" }, saved_at: "2026-09-06T10:00:00Z" }] };
    } else if (url.pathname.endsWith("/latest")) {
      json = { response: { symbol, timeframe: "1h", signal: "SHORT", result: { fold_count: 0 }, report: null } };
    } else if (url.pathname.endsWith("/filtered-summary")) {
      json = { result: { total_trades: 2, wins: 1, losses: 1, win_rate: 50, max_drawdown: 3, trades: [] } };
    } else if (url.pathname.endsWith("strategy-comparison/jobs")) {
      json = { status: "COMPLETED", response: { results: [], limitations: [], start: "2026-09-01", end: "2026-09-06", price_bars: 0, price_coverage_percent: 0, initial_capital_inr: 200000 } };
    }
    await route.fulfill({ json, headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:5173", "Access-Control-Allow-Credentials": "true" } });
  });
  await page.route("**/__wait-test", (route) => route.fulfill({ contentType: "text/html", body: `<!doctype html><div id="test-root"></div>
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
      const {default: Backtest} = await import('/src/pages/BacktestPage.jsx');
      function Test() {
        const [symbol, setSymbol] = React.useState('SOLUSDT');
        return React.createElement(React.Fragment, null,
          React.createElement('button', {onClick:()=>setSymbol('ETHUSDT')}, 'Switch test coin'),
          React.createElement(Backtest, {view:{symbol,timeframe:'1h',mode:'intraday'},selectedDetail:{signalType:'WAIT'}}));
      }
      createRoot(document.getElementById('test-root')).render(React.createElement(Test));
    </script>` }));
  await page.goto("http://127.0.0.1:5173/__wait-test");
  await page.getByText("2 closed trades", { exact: true }).waitFor({ timeout: 20000 });
  assert(requests.some((url) => url.pathname.endsWith("/filtered-summary") && url.searchParams.get("signal") === "SHORT"));
  await page.getByRole("button", { name: "Switch test coin" }).click();
  await page.getByText("No saved directional replay", { exact: true }).waitFor();
  assert.equal(await page.getByText("2 closed trades", { exact: true }).count(), 0);
  assert.equal(await page.getByText("Daily PNL", { exact: true }).count(), 1); // chart only, no empty metric card
  assert(!requests.some((url) => url.pathname.endsWith("/filtered-summary") && url.searchParams.get("symbol") === "ETHUSDT"));
  assert.deepEqual(errors, []);
  console.log("PASS: WAIT loads saved SHORT results; coin switch clears old results; absent history does not invent trades");
} finally { await browser.close(); }
