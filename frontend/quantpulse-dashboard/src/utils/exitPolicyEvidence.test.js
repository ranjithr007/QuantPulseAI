import assert from "node:assert/strict";
import test from "node:test";
import { exitPolicyEvidence } from "./exitPolicyEvidence.js";

test("uses recorded initial stop, not a trailing stop or display fallback", () => {
  const data = exitPolicyEvidence({ entry_price: 100, stop_loss: 102, recorded_initial_stop_loss: 99.25, recorded_exit_policy: "PAPER_ATR_STRUCTURE_V1" });
  assert.equal(data.distancePercent, .75);
  assert.equal(data.policy, "PAPER_ATR_STRUCTURE_V1");
  assert.equal(exitPolicyEvidence({ entry_price: 100, initial_stop_loss: 99, exit_policy: "FALLBACK" }).policy, "Not recorded");
});
test("supports shorts and rejects absent or invalid stops", () => {
  assert.equal(exitPolicyEvidence({ entry_price: 100, recorded_initial_stop_loss: 100.75 }).distancePercent, .75);
  for (const stop of [null, undefined, NaN, Infinity, 0]) {
    assert.equal(exitPolicyEvidence({ entry_price: 100, recorded_initial_stop_loss: stop }).distancePercent, null);
  }
});
