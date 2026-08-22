const IST_TIME_ZONE = "Asia/Kolkata";
const ISO_TIMESTAMP_WITHOUT_ZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

export function formatPrice(value, options = {}) {
  const { fallback = "N/A", fixedDigits = null, compactSmall = false } = normalizeOptions(options);
  if (value === null || value === undefined || Number.isNaN(Number(value))) return fallback;

  const number = Number(value);
  const absolute = Math.abs(number);
  const digits =
    fixedDigits !== null
      ? compactSmall && absolute < 2
        ? 5
        : fixedDigits
      : absolute >= 1000
        ? 2
        : absolute >= 100
          ? 2
          : absolute >= 1
            ? 4
            : absolute >= 0.1
              ? 5
              : 6;

  return number.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatSigned(value, digits = 2, fallback = "N/A") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return fallback;
  const number = Number(value);
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function formatPercent(value, digits = 1, fallback = "N/A") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return fallback;
  return `${Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })}%`;
}

export function formatNumber(value, digits = 2, fallback = "N/A") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return fallback;
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatCurrency(value, digits = 2, fallback = "N/A") {
  return formatNumber(value, digits, fallback);
}

export function formatInr(value, digits = 0, fallback = "N/A") {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return number.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatTargets(targets, fallback = "N/A") {
  if (!targets) return fallback;
  if (Array.isArray(targets)) {
    const values = targets.filter((value) => value !== null && value !== undefined);
    return values.length ? values.map((value) => formatPrice(value, { fallback })).join(" / ") : fallback;
  }

  return (
    [targets.target1, targets.target2, targets.target3]
      .filter((value) => value !== null && value !== undefined)
      .map((value) => formatPrice(value, { fallback }))
      .join(" / ") || fallback
  );
}

export function formatLevels(levels, fallback = "N/A") {
  if (!levels) return fallback;
  return [levels.r1, levels.r2, levels.r3, levels.s1, levels.s2, levels.s3]
    .map((value) => formatPrice(value, { fallback }))
    .join(" / ");
}

export function formatDate(value, fallback = "N/A") {
  if (!value) return fallback;
  const date = parseTimestamp(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${date.toLocaleString("en-IN", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: IST_TIME_ZONE,
  })} IST`;
}

export function formatTimeInIst(value, fallback = "N/A") {
  if (!value) return fallback;
  const date = parseTimestamp(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${date.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: IST_TIME_ZONE,
  })} IST`;
}

export function timestampMillis(value, fallback = 0) {
  if (!value) return fallback;
  const timestamp = parseTimestamp(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : fallback;
}

export function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function tooltipStyle() {
  return {
    background: "#020617",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 16,
    color: "#e2e8f0",
  };
}

function normalizeOptions(options) {
  if (typeof options === "number") {
    return { fixedDigits: options };
  }
  return options || {};
}

function parseTimestamp(value) {
  if (value instanceof Date || typeof value === "number") return new Date(value);

  const raw = String(value).trim();
  // FastAPI serializes the application's UTC database datetimes without a
  // suffix. JavaScript otherwise treats those values as browser-local time.
  const normalized = ISO_TIMESTAMP_WITHOUT_ZONE.test(raw) ? `${raw}Z` : raw;
  return new Date(normalized);
}
