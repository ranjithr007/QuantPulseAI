// Isolated Strategies UI: mocked API only, no real trading/server calls.
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { createServer } from "vite";

const server = await createServer({
  define: { "import.meta.env.VITE_BACKEND_URL": JSON.stringify("http://127.0.0.1:5181/api/") },
  server: { port: 5181, strictPort: true, open: false },
});
await server.listen();
let browser;
let page;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  page = await browser.newPage();
  await page.clock.install();
  const errors = [];
  page.on("pageerror", error => { errors.push(error.message); console.error(error.message); });
  let summaries = 0, ledgers = 0, summaryFailure = 0, ledgerFailure = 0;
  const headers = {"Access-Control-Allow-Origin":"http://127.0.0.1:5181", "Access-Control-Allow-Credentials":"true"};
  const record = {id:"CORE_SIGNAL", version:"test_v1", name:"Synthetic Core Signal", status:"ACTIVE", ledger_loaded:false};
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let status = 200, json;
    if (path.endsWith("/strategies/summary")) {
      summaries++;
      status = summaryFailure || 200;
      json = {records:[{...record, description:`Snapshot ${summaries}`}]};
    } else if (path.endsWith("/strategies/ledger")) {
      ledgers++;
      status = ledgerFailure || 200;
      json = {records:[{...record, ledger_loaded:true, strategy_paper_wallet:{wallet_balance_inr:187654}, strategy_paper_history:[]}]};
    } else throw new Error(`Unexpected API request: ${path}`);
    await route.fulfill({status,json,headers});
  });
  await page.route("**/__strategy-refresh", route => route.fulfill({contentType:"text/html",body:`
    <!doctype html><div id="root"></div><script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => (type) => type;
      window.__vite_plugin_react_preamble_installed__ = true;
      const r = await import('/node_modules/.vite/deps/react.js'); const React = r.default || r;
      const d = await import('/node_modules/.vite/deps/react-dom_client.js'); const {createRoot} = d.default || d;
      const {default: Strategies} = await import('/src/pages/StrategiesPage.jsx');
      let hidden = false;
      Object.defineProperty(document, 'visibilityState', {get:()=>hidden?'hidden':'visible'});
      createRoot(document.getElementById('root')).render(React.createElement(React.Fragment,null,
        React.createElement('button',{onClick:()=>{hidden=!hidden;document.dispatchEvent(new Event('visibilitychange'));}},'Toggle visibility'),
        React.createElement(Strategies)));
    </script>`}));
  await page.goto("http://127.0.0.1:5181/__strategy-refresh");
  await page.getByText("Snapshot 1",{exact:true}).waitFor();
  await page.getByText("₹1,87,654.00",{exact:true}).waitFor();
  assert.equal(summaries,1); assert.equal(ledgers,1);
  await page.clock.runFor(60100);
  await page.getByText("Snapshot 2",{exact:true}).waitFor();
  await page.getByRole('button',{name:'Refresh',exact:true}).waitFor();
  summaryFailure = 503;
  await page.clock.runFor(60100);
  await page.getByRole('alert').filter({hasText:'HTTP 503'}).waitFor();
  assert.equal(await page.getByText("Snapshot 2",{exact:true}).count(),1);
  await page.getByText(/Decisions loaded:.*STALE DISPLAY/).waitFor();
  summaryFailure = 0;
  await page.clock.runFor(5100);
  await page.getByText("Snapshot 4",{exact:true}).waitFor();
  await page.getByRole('alert').waitFor({state:'hidden'});
  ledgerFailure = 502;
  await page.clock.runFor(60100);
  await page.getByText(/Wallet\/history loaded:.*STALE DISPLAY/).waitFor();
  assert.equal(await page.getByText("₹1,87,654.00",{exact:true}).count(),1);
  ledgerFailure = 0;
  await page.clock.runFor(5100);
  await page.getByText(/Wallet\/history loaded:.*STALE DISPLAY/).waitFor({state:'hidden'});
  await page.getByRole('button',{name:'Toggle visibility'}).click();
  await page.getByText(/Automatic refresh paused while hidden/).waitFor();
  const hiddenCalls = summaries;
  await page.clock.runFor(180100);
  assert.equal(summaries,hiddenCalls);
  await page.getByRole('button',{name:'Toggle visibility'}).click();
  await page.getByText(`Snapshot ${hiddenCalls+1}`,{exact:true}).waitFor();
  summaryFailure = 403;
  await page.clock.runFor(60100);
  await page.getByRole('alert').filter({hasText:'access denied'}).waitFor();
  const deniedCalls = summaries;
  await page.clock.runFor(180100);
  assert.equal(summaries,deniedCalls);
  assert.deepEqual(errors,[]);
  console.log('PASS: automatic refresh, summary/ledger retry and retention, stale labels, hidden pause/resume, permanent error stops');
} catch (error) {
  console.error((await page?.locator('body').innerText())?.slice(0,2500));
  throw error;
} finally { await browser?.close(); await server.close(); }
