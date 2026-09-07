export const EXIT_CLASSIFICATIONS = {
  INITIAL_STOP: "Initial stop",
  TRAILED_STOP_PRE_T1: "Trailing stop before T1",
  PROTECTED_STOP_AFTER_T1: "Protected stop after T1",
  TARGET2: "Target 2 completed",
  TIME_EXIT: "Holding-time exit",
  UNKNOWN_STOP: "Stop type not recorded",
  UNKNOWN: "Unknown / evidence unavailable",
};

export function tradeExitClassification(trade) {
  // A STOP result, profit, or current stop alone cannot prove the exit subtype.
  const key = trade?.exit_evidence?.classification;
  return Object.hasOwn(EXIT_CLASSIFICATIONS, key) ? key : "UNKNOWN";
}

export function tradeExitBreakdown(trades = []) {
  const counts = {};
  for (const trade of trades) {
    const key = tradeExitClassification(trade);
    counts[key] = (counts[key] || 0) + 1;
  }
  return Object.entries(counts).map(([key, count]) => ({ key, label: EXIT_CLASSIFICATIONS[key], count }));
}

export function recordedNumber(value) {
  if (value == null || value === "" || typeof value === "boolean") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function preTargetLosingStops(metrics = {}) {
  // V2 used initial_stop_failures for all pre-T1 losing stops. V3 narrows
  // that field to proven untouched initial stops, so it is not a fallback.
  return recordedNumber(metrics.pre_t1_losing_stops)
    ?? (metrics.metric_version === "STOP_CAUSE_COHORT_V3" ? null : recordedNumber(metrics.initial_stop_failures));
}
