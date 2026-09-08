import assert from "node:assert/strict";
import test from "node:test";
import { exitPolicyEvidence, trailingActivationLabel } from "./exitPolicyEvidence.js";

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

test("distinguishes recorded immediate and delayed trailing without assuming historical thresholds", () => {
  assert.equal(trailingActivationLabel({ trailing_activation_r: 0 }), "Immediate (0R)");
  assert.equal(trailingActivationLabel({ execution_evidence: { trailing_activation_r: 1 } }), "Delayed until 1R");
  assert.equal(trailingActivationLabel({ trailing_activation_r: 0, execution_evidence: { trailing_activation_r: 1 } }), "Immediate (0R)");
  for (const value of [undefined, null, "", " ", true, -1, 6, NaN, Infinity]) {
    assert.equal(trailingActivationLabel({ trailing_activation_r: value }), "Not recorded");
  }
  assert.equal(trailingActivationLabel({ execution_evidence: { exit_management_profile: "DELAYED_TRAIL_1R_V1" } }), "Not recorded");
});
