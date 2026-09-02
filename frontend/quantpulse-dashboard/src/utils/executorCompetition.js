export function normalizeExecutorSide(value) {
  const side = String(value || "").toUpperCase();
  if (["BUY", "LONG", "STRONG_LONG"].includes(side)) return "LONG";
  if (["SELL", "SHORT", "STRONG_SHORT"].includes(side)) return "SHORT";
  return side || null;
}

export function executorCandidatesForSymbol(candidates = [], symbol) {
  const normalizedSymbol = String(symbol || "").toUpperCase();
  return candidates.filter(
    (candidate) => String(candidate?.symbol || "").toUpperCase() === normalizedSymbol
  );
}

export function isCandidateExecutorReady(candidate) {
  if (!candidate) return false;
  if (candidate?.arbitration) {
    return candidate.arbitration.selected_for_official_execution === true;
  }
  return candidate.eligible === true;
}

export function candidateExecutorBlockers(candidate) {
  if (!candidate) return [];
  if (candidate?.arbitration) {
    return candidate.arbitration.executor_blockers || [];
  }
  return candidate.blocked_reasons || [];
}

function fallbackCandidateRank(candidate) {
  const plan = candidate?.trade_plan || {};
  const risk = candidate?.risk_decision || {};
  const timeframePriority = { "1h": 1, "2h": 2, "4h": 3, "1d": 4 };
  return [
    candidate?.eligible === true ? 1 : 0,
    Number(risk.confidence || 0),
    Number(plan.confidence || 0),
    Number(plan.risk_reward || 0),
    timeframePriority[String(plan.entry_timeframe || "").toLowerCase()] || 0,
    Date.parse(plan.created_at || "") || 0,
    Number(plan.id || 0),
  ];
}

function compareFallbackRank(left, right) {
  const leftRank = fallbackCandidateRank(left);
  const rightRank = fallbackCandidateRank(right);
  for (let index = 0; index < leftRank.length; index += 1) {
    if (leftRank[index] !== rightRank[index]) return rightRank[index] - leftRank[index];
  }
  return 0;
}

export function selectExecutorCandidate(candidates = [], symbol, preferredSide = null) {
  const symbolCandidates = executorCandidatesForSymbol(candidates, symbol);
  if (!symbolCandidates.length) return null;

  const selected = symbolCandidates.find(
    (candidate) => candidate?.arbitration?.selected_for_official_execution === true
  );
  if (selected) return selected;

  const normalizedSide = normalizeExecutorSide(preferredSide);
  const preferred = normalizedSide
    ? symbolCandidates.filter(
        (candidate) => normalizeExecutorSide(candidate?.side) === normalizedSide
      )
    : symbolCandidates;
  const pool = preferred.length ? preferred : symbolCandidates;

  return [...pool].sort((left, right) => {
    const leftRank = Number(left?.arbitration?.rank ?? Number.POSITIVE_INFINITY);
    const rightRank = Number(right?.arbitration?.rank ?? Number.POSITIVE_INFINITY);
    if (leftRank !== rightRank) return leftRank - rightRank;
    return compareFallbackRank(left, right);
  })[0];
}

export function executorStrategyLabel(candidate) {
  const plan = candidate?.trade_plan || {};
  return plan.strategy_name || plan.strategy_id || "selected strategy";
}
