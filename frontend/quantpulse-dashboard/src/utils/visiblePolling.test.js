import test from "node:test";
import assert from "node:assert/strict";
import { startVisiblePolling } from "./visiblePolling.js";

function environment() {
  let listener, next = 0;
  const queued = new Map();
  const page = { visibilityState: "visible", addEventListener: (_, fn) => { listener = fn; }, removeEventListener: () => { listener = null; } };
  const timers = { setTimeout: (fn, ms) => { queued.set(++next, {fn, ms}); return next; }, clearTimeout: id => queued.delete(id) };
  return {page, timers, queued, visibility(state) { page.visibilityState = state; listener?.(); }};
}
const settle = async () => { await Promise.resolve(); await Promise.resolve(); };

test("no overlapping reads; hidden abort resumes even during the abort race; cleanup stops scheduling", async () => {
  const env = environment();
  let resolve, calls = 0, signal;
  const stop = startVisiblePolling(s => { calls++; signal = s; return new Promise(r => { resolve = r; }); }, env);
  env.visibility("visible");
  assert.equal(calls, 1);
  env.visibility("hidden");
  assert.equal(signal.aborted, true);
  env.visibility("visible");
  assert.equal(calls, 1);
  resolve(60000); await settle();
  const [id, work] = [...env.queued][0];
  assert.equal(work.ms, 0);
  env.queued.delete(id); void work.fn();
  assert.equal(calls, 2);
  stop(); resolve(60000); await settle();
  assert.equal(signal.aborted, true);
  assert.equal(env.queued.size, 0);
});

test("initial hidden state makes no requests; null stops retries and supplied delay is respected", async () => {
  const env = environment(); env.page.visibilityState = "hidden";
  let calls = 0;
  const stop = startVisiblePolling(async () => { calls++; return calls === 1 ? 15000 : null; }, env);
  assert.equal(calls, 0);
  env.visibility("visible"); await settle();
  assert.equal([...env.queued.values()][0].ms, 15000);
  env.visibility("hidden");
  assert.equal(env.queued.size, 0);
  env.visibility("visible"); await settle();
  assert.equal(calls, 2);
  assert.equal(env.queued.size, 0);
  stop();
});
