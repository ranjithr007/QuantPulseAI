const HUMANIZED_STATUS_OVERRIDES = {
  historical_stale: "Historical data is stale",
  pipeline_unknown: "Pipeline unknown",
  current_invalid: "Current signal is invalid",
  no_data: "No data",
};

export function humanizeMachineStatus(value, fallback = "-") {
  const raw = String(value || "").trim();
  if (!raw) return fallback;

  if (/\s/.test(raw) && /[a-z]/.test(raw)) {
    return raw;
  }

  const normalized = raw.toLowerCase();
  if (HUMANIZED_STATUS_OVERRIDES[normalized]) {
    return HUMANIZED_STATUS_OVERRIDES[normalized];
  }

  return raw
    .replace(/[_-]+/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}
