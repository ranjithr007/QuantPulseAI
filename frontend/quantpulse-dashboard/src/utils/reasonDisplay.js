function normalizeReason(reason) {
  return String(reason || "").trim().replace(/\s+/g, " ").toLowerCase();
}

export function dedupeReasonList(reasons = []) {
  const seen = new Set();
  return reasons.filter((reason) => {
    if (!reason) {
      return false;
    }
    const key = normalizeReason(reason);
    if (!key || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

export function buildRiskBlockPills({ autoReasons = [], validationErrors = [], ignoredReasons = [] } = {}) {
  const primaryReasons = dedupeReasonList(autoReasons);
  const validationList = dedupeReasonList(validationErrors).filter(
    (reason) => !primaryReasons.some((value) => normalizeReason(value) === normalizeReason(reason)),
  );
  const ignoredList = primaryReasons.length || validationList.length
    ? []
    : dedupeReasonList(ignoredReasons).filter(
        (reason) => !primaryReasons.some((value) => normalizeReason(value) === normalizeReason(reason)),
      );

  return [
    ...primaryReasons.map((reason) => ({ reason, tone: "rose" })),
    ...validationList.map((reason) => ({ reason, tone: "rose" })),
    ...ignoredList.map((reason) => ({ reason, tone: "amber" })),
  ];
}
