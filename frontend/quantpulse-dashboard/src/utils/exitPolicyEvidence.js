export function exitPolicyEvidence(trade) {
  const entry = Number(trade?.entry_price);
  const stop = Number(trade?.recorded_initial_stop_loss);
  const valid = trade?.recorded_initial_stop_loss != null && Number.isFinite(entry) && entry > 0 && Number.isFinite(stop) && stop > 0;
  return {
    policy: trade?.recorded_exit_policy || "Not recorded",
    initialStop: valid ? stop : null,
    distancePercent: valid ? Math.abs(entry - stop) / entry * 100 : null,
  };
}

export function trailingActivationLabel(trade) {
  // A policy name or current stop cannot establish a historical activation threshold.
  const recorded = trade?.trailing_activation_r ?? trade?.execution_evidence?.trailing_activation_r;
  if (recorded == null || typeof recorded === "boolean" || String(recorded).trim() === "") return "Not recorded";
  const activation = Number(recorded);
  if (!Number.isFinite(activation) || activation < 0 || activation > 5) return "Not recorded";
  return activation === 0 ? "Immediate (0R)" : `Delayed until ${activation}R`;
}
