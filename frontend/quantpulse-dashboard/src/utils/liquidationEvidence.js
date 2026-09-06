import { formatNumber, formatTimeInIst, timestampMillis } from "./formatters.js";

export function liquidationEngineEvidence(evidence = {}, now = Date.now()) {
  const latest = timestampMillis(evidence.source_timestamp, NaN);
  const age = (now - latest) / 1000;
  const longValue = evidence.long_liquidation_usd;
  const shortValue = evidence.short_liquidation_usd;
  const valid = evidence.direction_method === "ORDER_SIDE_V1"
    && evidence.data_quality === "OBSERVED"
    && evidence.freshness?.is_stale === false
    && Number.isFinite(age) && age >= -1 && age <= 1800
    && Number.isFinite(longValue) && longValue >= 0
    && Number.isFinite(shortValue) && shortValue >= 0
    && longValue + shortValue > 0;
  const hours = Number(evidence.window_seconds) / 3600;
  const windowLabel = Number.isFinite(hours) && hours > 0 ? `${hours}h window` : "Window unavailable";
  const details = `${windowLabel} · Longs $${formatNumber(longValue, 2)} · Shorts $${formatNumber(shortValue, 2)} · Latest ${formatTimeInIst(evidence.source_timestamp)}`;
  if (!valid) {
    return { score: null, reason: "Fresh order-side liquidation evidence unavailable", details };
  }
  const score = Math.round(10000 * (shortValue - longValue) / (shortValue + longValue)) / 100;
  return {
    score,
    reason: score > 0 ? "Observed short liquidations: forced buying"
      : score < 0 ? "Observed long liquidations: forced selling" : "Observed liquidation values are balanced",
    details: `${details} · Binance sampled events; not a continuation forecast`,
  };
}
