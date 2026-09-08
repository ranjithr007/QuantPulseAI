import assert from "node:assert/strict";
import test from "node:test";
import { entryStructureEvidence } from "./entryStructureEvidence.js";

test("renders only the structure and gate outcome recorded at entry", () => {
  const evidence = entryStructureEvidence({ execution_evidence: {
    entry_quality_profile: "CONFIRMED_PRICE_STRUCTURE_V1",
    setup_type: "BREAKOUT_RETEST",
    structure_timeframe: "5m",
    structure_closed_at: "2026-09-08T10:00:00Z",
    structure_level: 100,
    structure_invalidation_level: 99,
    entry_quality_passed: true,
  } });
  assert.equal(evidence.profile, "CONFIRMED_PRICE_STRUCTURE_V1");
  assert.equal(evidence.setupType, "BREAKOUT_RETEST");
  assert.equal(evidence.timeframe, "5m");
  assert.equal(evidence.closedAt, "2026-09-08T10:00:00Z");
  assert.equal(evidence.level, 100);
  assert.equal(evidence.invalidationLevel, 99);
  assert.equal(evidence.qualityPassed, true);
  assert.equal(evidence.hasStructureEvidence, true);
});

test("bullish scores, entry timeframe, and profile names do not prove structure or gate passage", () => {
  for (const profile of [undefined, "BASELINE", "MARKET_MOVE_BASELINE_V1", "CONFIRMED_PRICE_STRUCTURE_V1"]) {
    const evidence = entryStructureEvidence({ side: "LONG", score: 99, entry_timeframe: "5m", execution_evidence: { entry_quality_profile: profile } });
    assert.equal(evidence.profile, profile || null);
    assert.equal(evidence.hasStructureEvidence, false);
    assert.equal(evidence.timeframe, null);
    assert.equal(evidence.qualityPassed, null);
  }
});

test("missing gate evidence is not failure and truthy strings are not recorded passage", () => {
  for (const entry_quality_passed of [null, undefined, "true", 1]) {
    assert.equal(entryStructureEvidence({ execution_evidence: { entry_quality_passed } }).qualityPassed, null);
  }
  assert.equal(entryStructureEvidence({ execution_evidence: { entry_quality_passed: false } }).qualityPassed, false);
});

test("supports recorded nested structure without replacing explicit flattened evidence", () => {
  const evidence = entryStructureEvidence({ execution_evidence: {
    setup_type: "PULLBACK",
    structure_level: null,
    entry_structure: { setup_type: "BREAKOUT_RETEST", structure_level: 100, structure_timeframe: "15m" },
  } });
  assert.equal(evidence.setupType, "PULLBACK");
  assert.equal(evidence.level, null);
  assert.equal(evidence.timeframe, "15m");
});
