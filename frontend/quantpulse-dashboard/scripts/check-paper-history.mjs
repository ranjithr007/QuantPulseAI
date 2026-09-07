// Local synthetic regression only. Start Vite on port 5179; no production data.
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
const browser = await chromium.launch({ channel: "chrome", headless: true });
const base = "http://127.0.0.1:5179";
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let pageOneCalls = 0, pageTwoCalls = 0;
  let failPageTwo = true, waitForPageTwo;
  const fixture = (number) => ({ page: number, page_size: 10, total_count: 20, records: [{
    id: number, symbol: number === 1 ? "FIRSTUSDT" : "SECONDUSDT", side: "LONG",
    entry_price: 100, exit_price: 100.05, pnl_percent: -.14,
    gross_pnl_percent: .05, fees_percent: .15, funding_cost_percent: null, result: "LOSS",
    ...(number === 2 ? { exit_evidence: { classification: "TRAILED_STOP_PRE_T1", active_stop_before_trigger: 100.05, evidence_kind: "LIVE_MARK", observations: { mfe_percent: .8, mae_percent: -.1 } } } : {}),
  }] });
  await page.route("**/paper-trade/trades?**", async (route) => {
    const number = Number(new URL(route.request().url()).searchParams.get("page"));
    if (number === 1) pageOneCalls++; else pageTwoCalls++;
    if (number === 2 && waitForPageTwo) await waitForPageTwo;
    await route.fulfill({ status: number === 2 && failPageTwo ? 504 : 200,
      json: number === 2 && failPageTwo ? { detail: "synthetic timeout" } : fixture(number),
      headers: { "Access-Control-Allow-Origin": base, "Access-Control-Allow-Credentials": "true" } });
  });
  await page.route("**/__paper-history-test", (route) => route.fulfill({ contentType: "text/html", body: `<!doctype html><div id="test-root"></div>
    <script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type;
      window.__vite_plugin_react_preamble_installed__=true;
      const reactModule=await import('/node_modules/.vite/deps/react.js');
      const React=reactModule.default || reactModule;
      const rootModule=await import('/node_modules/.vite/deps/react-dom_client.js');
      const {createRoot}=rootModule.default || rootModule;
      const {default: History}=await import('/src/components/PaperTradeHistory.jsx');
      createRoot(document.getElementById('test-root')).render(React.createElement(History,{tradeHistory:[{id:1}],totalCount:20}));
    </script>` }));
  await page.goto(`${base}/__paper-history-test`);
  await page.getByRole("cell", { name: "FIRSTUSDT", exact: true }).waitFor();
  await page.getByRole("button", { name: "View audit FIRSTUSDT trade 1" }).click();
  await page.getByRole("dialog").waitFor();
  assert.match(await page.getByRole("dialog").innerText(), /Exit trigger evidence unavailable/);
  assert.match(await page.getByRole("dialog").innerText(), /Funding\s+Not recorded/);
  await page.keyboard.press("Escape");
  assert.equal(await page.getByRole("dialog").count(), 0);
  let release;
  waitForPageTwo = new Promise((resolve) => { release = resolve; });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByText("Loading page 2…", { exact: true }).waitFor();
  assert.equal(await page.getByRole("cell", { name: "FIRSTUSDT", exact: true }).count(), 0);
  release(); waitForPageTwo = null;
  await page.getByRole("alert").waitFor();
  assert.equal(await page.getByRole("cell", { name: "FIRSTUSDT", exact: true }).count(), 0);
  assert.match(await page.getByRole("alert").innerText(), /Page 2 could not be loaded/);
  failPageTwo = false;
  await page.getByRole("button", { name: "Retry page", exact: true }).click();
  await page.getByRole("cell", { name: "SECONDUSDT", exact: true }).waitFor();
  assert.equal(pageTwoCalls, 2);
  await page.getByRole("button", { name: "View audit SECONDUSDT trade 2" }).click();
  assert.match(await page.getByRole("dialog").innerText(), /Trailing stop before T1/);
  await page.getByRole("button", { name: "Close audit" }).click();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await page.getByRole("cell", { name: "FIRSTUSDT", exact: true }).waitFor();
  assert.equal(pageOneCalls, 1, "returning to same snapshot uses bounded page cache");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("cell", { name: "SECONDUSDT", exact: true }).waitFor();
  waitForPageTwo = new Promise((resolve) => { release = resolve; });
  await page.getByRole("button", { name: "Refresh page", exact: true }).click();
  await page.getByText("Loading page 2…", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await page.getByRole("cell", { name: "FIRSTUSDT", exact: true }).waitFor();
  release(); waitForPageTwo = null;
  await page.getByText(/Showing 1–1 of 20 closed trades · page 1/).waitFor();
  assert.equal(await page.getByRole("cell", { name: "SECONDUSDT", exact: true }).count(), 0);
  const stalledBody = await page.evaluate(async () => {
    const {loadPaperTrades}=await import('/src/hooks/dashboardApi.js');
    const realFetch=window.fetch, realTimeout=window.setTimeout;
    window.setTimeout=(fn)=>realTimeout(fn,25);
    window.fetch=async (_url,{signal})=>({ok:true,json:()=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true}))});
    try { await loadPaperTrades(); return 'unexpected success'; }
    catch(error) { return error.message; }
    finally { window.fetch=realFetch; window.setTimeout=realTimeout; }
  });
  assert.match(stalledBody, /timed out after 20 seconds/);
  assert.deepEqual(errors, []);
  console.log("PASS: page timeout hides old rows; retry recovers; cache is page-correct; canceled late response ignored; legacy audit honest; body timeout bounded.");
} finally { await browser.close(); }
