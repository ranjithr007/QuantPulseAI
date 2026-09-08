import { recordedNumber } from "./tradeAudit.js";

export function entryStructureEvidence(trade) {
  const entry = trade?.execution_evidence || {};
  const structure = entry.entry_structure || {};
  const recorded = (field) => Object.hasOwn(entry, field) ? entry[field] : structure[field];
  const evidence = {
    profile: entry.entry_quality_profile || null,
    setupType: recorded("setup_type") || null,
    timeframe: recorded("structure_timeframe") || null,
    closedAt: recorded("structure_closed_at") || null,
    level: recordedNumber(recorded("structure_level")),
    invalidationLevel: recordedNumber(recorded("structure_invalidation_level")),
    qualityPassed: typeof entry.entry_quality_passed === "boolean" ? entry.entry_quality_passed : null,
  };
  return {
    ...evidence,
    hasStructureEvidence: [evidence.setupType, evidence.timeframe, evidence.closedAt, evidence.level, evidence.invalidationLevel].some((value) => value != null),
  };
}
