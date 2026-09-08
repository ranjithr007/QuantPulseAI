// Synthetic UI test only: all API traffic is intercepted; no paper orders.
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { createServer } from "vite";

const server = await createServer({ server: { port: 5179, open: false } });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage();
  await page.clock.install();
  const errors = [], requests = [];
  let submissions = 0, polls = 0, notifications = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  const headers = { "Access-Control-Allow-Origin": "http://127.0.0.1:5179", "Access-Control-Allow-Credentials": "true" };
  const report = { start: "2026-09-01", end: "2026-09-08", price_bars: 2015,
    initial_capital_inr: 200000, price_coverage_percent: 99.95, limitations: ["Synthetic saved replay"], results: [] };
  await page.route("**/backtest/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.pathname);
    let status = 200, json;
    if (url.pathname.endsWith("strategy-comparison/jobs")) {
      submissions++;
      if (url.searchParams.get("symbol") === "ETHUSDT") { status = 403; json = {}; }
      else if (submissions === 1) { status = 503; json = {}; }
      else if (submissions === 2) json = {status: "COMPLETED", response: report};
      else json = {status: "QUEUED", job_id: "known-job"};
    } else {
      polls++;
      if (polls === 1) { status = 502; json = {}; }
      else json = {status: "COMPLETED", response: {...report, price_bars: 2020}};
    }
    await route.fulfill({status, json, headers});
  });
  await page.route("**/notifications**", async (route) => {
    if (route.request().url().includes("unread-count")) return route.fulfill({json: {unreadCount: 1}, headers});
    notifications++;
    if ([1, 3].includes(notifications)) return route.fulfill({status: 503, json: {}, headers});
    await route.fulfill({json: {unreadCount: 1, records: [{id: 1, title: "Saved test alert", message: "Retained during retry", category: "SYSTEM", isRead: true, createdAt: "2026-09-08T10:00:00Z"}]}, headers});
  });
  await page.route("**/__request-recovery", (route) => route.fulfill({contentType: "text/html", body: `
    <!doctype html><div id="test-root"></div><script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$ = () => {};
      window.$RefreshSig$ = () => (type) => type;
      window.__vite_plugin_react_preamble_installed__ = true;
      const reactModule = await import('/node_modules/.vite/deps/react.js');
      const React = reactModule.default || reactModule;
      const rootModule = await import('/node_modules/.vite/deps/react-dom_client.js');
      const {createRoot} = rootModule.default || rootModule;
      const {default: Replay} = await import('/src/components/StrategyBacktestComparison.jsx');
      const {default: Notifications} = await import('/src/components/NotificationCenter.jsx');
      function Fixture() {
        const [symbol, setSymbol] = React.useState('BTCUSDT');
        return React.createElement(React.Fragment, null,
          React.createElement('button', {onClick:()=>setSymbol('ETHUSDT')}, 'Switch coin'),
          React.createElement(Notifications, {}), React.createElement(Replay, {symbol}));
      }
      createRoot(document.getElementById('test-root')).render(React.createElement(Fixture));
    </script>`}));
  await page.goto("http://127.0.0.1:5179/__request-recovery");
  await page.getByText(/Strategy replay: server returned HTTP 503/).waitFor();
  await page.clock.runFor(5100);
  await page.getByText("Synthetic saved replay", {exact: true}).waitFor();
  await page.clock.fastForward(3600001);
  await page.getByText(/Showing the previous completed replay/).waitFor();
  assert.equal(await page.getByText("Synthetic saved replay", {exact: true}).count(), 1);
  await page.clock.runFor(5100);
  await page.getByText(/Strategy replay: server returned HTTP 502/).waitFor();
  assert.equal(await page.getByText("Synthetic saved replay", {exact: true}).count(), 1);
  await page.clock.runFor(5100);
  await page.getByText(/2020 verified 5m bars/).waitFor();
  assert.equal(submissions, 3);
  assert.equal(polls, 2);
  assert.equal(requests.filter((path) => path.endsWith("known-job")).length, 2);
  await page.getByRole("button", {name: "Switch coin", exact: true}).click();
  await page.getByText("Strategy replay: access denied.", {exact: true}).waitFor();
  assert.equal(await page.getByText("Synthetic saved replay", {exact: true}).count(), 0);
  const before = submissions;
  await page.clock.runFor(61000);
  assert.equal(submissions, before);
  await page.getByRole("button", {name: "1 unread notifications", exact: true}).click();
  await page.getByText(/Notifications: server returned HTTP 503/).waitFor();
  await page.clock.runFor(5100);
  await page.getByText("Saved test alert", {exact: true}).waitFor();
  await page.clock.runFor(30100);
  await page.getByText(/Showing previously loaded notifications/).waitFor();
  assert.equal(await page.getByText("Saved test alert", {exact: true}).count(), 1);
  await page.clock.runFor(5100);
  await page.getByText(/Showing previously loaded notifications/).waitFor({state: "hidden"});
  await page.getByRole("button", {name: "Close notifications", exact: true}).click();
  const closedCount = notifications;
  await page.clock.runFor(61000);
  assert.equal(notifications, closedCount);
  assert.deepEqual(errors, []);
  console.log("PASS: automatic replay retry, known-job polling, cached result retention, scope reset, permanent-error stop, notification retry/retention/close cancellation");
} finally {
  await browser?.close();
  await server.close();
}
