import assert from "node:assert/strict";
import test from "node:test";
import { preTargetLosingStops, recordedNumber, tradeExitBreakdown, tradeExitClassification } from "./tradeAudit.js";

test("legacy losing or profitable stops cannot be inferred as initial stops", () => {
  for (const pnl_percent of [-1, 0, 2]) assert.equal(tradeExitClassification({ exit_reason: "STOP", pnl_percent }), "UNKNOWN");
  assert.equal(tradeExitClassification({ exit_evidence: { classification: "INVENTED" } }), "UNKNOWN");
});
test("recorded categories remain separate in page-only breakdown", () => {
  const trades = ["INITIAL_STOP", "TRAILED_STOP_PRE_T1", "PROTECTED_STOP_AFTER_T1", "TARGET2", "TIME_EXIT", "UNKNOWN_STOP"].map((classification) => ({ exit_evidence: { classification } }));
  const counts = tradeExitBreakdown([...trades, {}]);
  assert.equal(counts.length, 7);
  assert.equal(counts.find((item) => item.key === "UNKNOWN").count, 1);
});
test("missing evidence is never coerced to zero", () => {
  for (const value of [undefined, null, "", false, "oops", Infinity]) assert.equal(recordedNumber(value), null);
  assert.equal(recordedNumber(0), 0);
  assert.equal(recordedNumber("0.15"), 0.15);
});
test("V3 initial stops are not mislabeled as all pre-T1 losing stops", () => {
  assert.equal(preTargetLosingStops({ initial_stop_failures: 10 }), 10);
  assert.equal(preTargetLosingStops({ metric_version: "STOP_CAUSE_COHORT_V3", initial_stop_failures: 2, pre_t1_losing_stops: 10 }), 10);
  assert.equal(preTargetLosingStops({ metric_version: "STOP_CAUSE_COHORT_V3", initial_stop_failures: 2 }), null);
});
