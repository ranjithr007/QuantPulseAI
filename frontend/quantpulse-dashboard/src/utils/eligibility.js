import { humanizeMachineStatus } from "./text";

export function deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades = [] }) {
  if (auto?.emergencyStop) {
    return {
      label: "Emergency stop",
      note: "Automatic execution is halted until emergency stop is cleared.",
      tone: "rose",
    };
  }

  if (auto?.locked) {
    return {
      label: "Auto trading locked",
      note: "Unlock futures auto trading before any signal can become eligible.",
      tone: "amber",
    };
  }

  if (autoDecision?.allowed && openTrades.length === 0) {
    return {
      label: "Ready to execute",
      note: "Signal passes automation checks and is waiting for the futures paper-trade executor.",
      tone: "emerald",
    };
  }

  if (autoDecision?.allowed) {
    return {
      label: "Eligible",
      note: "Selected futures contract passes automation checks.",
      tone: "emerald",
    };
  }

  if (selectedRisk?.is_usable === false || selectedRisk?.decision === "REJECT") {
    return {
      label: "Blocked by risk",
      note: humanizeMachineStatus(selectedRisk?.status, autoDecision?.reason || "Risk decision rejected."),
      tone: "rose",
    };
  }

  const confidence = Number(selectedDetail?.confidence || 0);
  const minConfidence = Number(auto?.minConfidence || 0);
  if (confidence < minConfidence) {
    return {
      label: "Blocked by confidence",
      note: `Confidence must be at least ${minConfidence}%.`,
      tone: "amber",
    };
  }

  return {
    label: "Blocked",
    note: humanizeMachineStatus(autoDecision?.reason, "Rule check failed."),
    tone: "rose",
  };
}

export function deriveRowEligibilityState({ row, watchRow, minConfidence = 40 }) {
  if (watchRow?.eligibility_label) {
    const riskSource = String(watchRow?.risk_source || "").toLowerCase();
    const sourceLabel = riskSource === "persisted"
      ? "Persisted risk"
      : riskSource === "computed"
        ? "Computed risk"
        : "Trigger fallback";

    return {
      label: String(watchRow.eligibility_label),
      tone: String(watchRow.eligibility_tone || "slate"),
      note: watchRow?.eligibility_reason
        ? `${sourceLabel}: ${humanizeMachineStatus(watchRow.eligibility_reason, watchRow.eligibility_reason)}`
        : humanizeMachineStatus(watchRow?.reason, sourceLabel),
    };
  }

  const confidence = Number(row?.confidence || 0);
  const riskReward = Number(row?.riskReward || watchRow?.risk_reward || 0);
  const failedConditions = Array.isArray(watchRow?.failed_conditions) ? watchRow.failed_conditions.map((value) => String(value).toLowerCase()) : [];
  const riskHints = [
    row?.reason,
    watchRow?.reason,
    watchRow?.trade_permission,
    ...failedConditions,
  ]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());

  if (row?.type === "WAIT" || String(watchRow?.status || "").toUpperCase() === "WAIT") {
    return { label: "Blocked", tone: "rose", note: humanizeMachineStatus(row?.reason || watchRow?.reason, "No actionable signal.") };
  }

  if (confidence < Number(minConfidence || 0)) {
    return {
      label: "Blocked by confidence",
      tone: "amber",
      note: `Needs ${minConfidence}% minimum confidence.`,
    };
  }

  if (
    riskReward > 0 && riskReward < 1.3 ||
    riskHints.some((value) => value.includes("risk")) ||
    riskHints.some((value) => value.includes("stop")) ||
    riskHints.some((value) => value.includes("drawdown"))
  ) {
    return {
      label: "Blocked by risk",
      tone: "rose",
      note: humanizeMachineStatus(watchRow?.reason || row?.reason, "Risk gate conditions are not met."),
    };
  }

  return {
    label: "Eligible",
    tone: "emerald",
    note: "Signal passes row-level eligibility checks.",
  };
}
