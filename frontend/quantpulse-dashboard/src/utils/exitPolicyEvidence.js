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
