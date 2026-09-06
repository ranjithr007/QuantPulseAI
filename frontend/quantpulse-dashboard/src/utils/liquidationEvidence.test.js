import assert from "node:assert/strict";
import test from "node:test";
import { liquidationEngineEvidence } from "./liquidationEvidence.js";

const now = Date.parse("2026-09-04T14:00:00Z");
const evidence = { direction_method: "ORDER_SIDE_V1", data_quality: "OBSERVED",
  freshness: { is_stale: false }, source_timestamp: "2026-09-04T13:59:00",
  window_seconds: 14400, long_liquidation_usd: 800000, short_liquidation_usd: 200000 };

test("long forced sells yield measured -60, not a fixed positive score", () => {
  const result = liquidationEngineEvidence(evidence, now);
  assert.equal(result.score, -60);
  assert.match(result.reason, /long liquidations/);
  assert.match(result.details, /4h window/);
  assert.match(result.details, /IST/);
});
test("short forced buys yield +60", () => {
  const result = liquidationEngineEvidence({ ...evidence, long_liquidation_usd: 200000, short_liquidation_usd: 800000 }, now);
  assert.equal(result.score, 60);
  assert.match(result.reason, /short liquidations/);
});
test("empty, legacy, stale and nonnumeric data never score", () => {
  for (const row of [{}, { data_quality: "OBSERVED", bias: "HUNT_SHORTS" },
    { ...evidence, source_timestamp: "2026-09-04T12:00:00Z" },
    { ...evidence, freshness: { is_stale: true } },
    { ...evidence, long_liquidation_usd: NaN },
    { ...evidence, long_liquidation_usd: 0, short_liquidation_usd: 0 }]) {
    assert.equal(liquidationEngineEvidence(row, now).score, null);
  }
});
test("equal sides are neutral", () => {
  assert.equal(liquidationEngineEvidence({ ...evidence, short_liquidation_usd: 800000 }, now).score, 0);
});
