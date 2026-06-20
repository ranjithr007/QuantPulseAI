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
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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
