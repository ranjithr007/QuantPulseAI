const LIVE_AFTER_MS = 30_000;
const FALLBACK_AFTER_MS = 120_000;

export function getLiveMarketState({ liveStatus, updatedAt, hasLiveRecord = false } = {}) {
  const ageSeconds = ageInSeconds(updatedAt);
  const connected = liveStatus?.connected ?? Boolean(liveStatus?.running);

  if (hasLiveRecord && ageSeconds !== null && ageSeconds <= LIVE_AFTER_MS / 1000) {
    return { state: "LIVE", label: "LIVE", source: "Auto refresh 10s", tone: "emerald", ageSeconds };
  }

  if (hasLiveRecord && ageSeconds !== null && ageSeconds <= FALLBACK_AFTER_MS / 1000) {
    return { state: "LIVE", label: "LIVE", source: "Auto refresh 10s", tone: "emerald", ageSeconds };
  }

  if (hasLiveRecord) {
    return { state: "FALLBACK", label: "DB", source: "DB Candle fallback", tone: "slate", ageSeconds };
  }

  if (connected) {
    return { state: "CONNECTING", label: "CONNECTING", source: "Waiting for live tick", tone: "amber", ageSeconds };
  }

  if (liveStatus?.running) {
    return { state: "RECONNECTING", label: "RECONNECTING", source: "Live feed reconnecting", tone: "amber", ageSeconds };
  }

  return { state: "FALLBACK", label: "DB", source: "DB Candle", tone: "slate", ageSeconds };
}

export function getCandleMarketState(freshness) {
  if (freshness?.is_stale === true) {
    return {
      state: "STALE",
      label: "STALE CANDLE",
      shortLabel: "STALE",
      source: "Stale DB candle",
      tone: "amber",
    };
  }

  if (freshness && typeof freshness === "object") {
    return {
      state: "FRESH",
      label: "FRESH CANDLE",
      shortLabel: "FRESH",
      source: "Synced DB candle",
      tone: "cyan",
    };
  }

  return {
    state: "UNKNOWN",
    label: "DB CANDLE",
    shortLabel: "DB",
    source: "DB candle status unavailable",
    tone: "slate",
  };
}

export function getUnifiedMarketState({ liveStatus, liveRecord, freshness } = {}) {
  const liveState = getLiveMarketState({
    liveStatus,
    updatedAt: liveRecord?.received_at || liveRecord?.event_time,
    hasLiveRecord: Boolean(liveRecord),
  });
  const candleState = getCandleMarketState(freshness);

  return {
    liveState,
    candleState,
    priceSource: liveState.state === "FALLBACK" ? candleState.source : liveState.source,
  };
}

export function liveStateClasses(tone) {
  return {
    emerald: "bg-emerald-500/10 text-emerald-200",
    amber: "bg-amber-500/10 text-amber-200",
    slate: "bg-slate-500/10 text-slate-200",
  }[tone] || "bg-slate-500/10 text-slate-200";
}

export function formatTickAge(ageSeconds) {
  if (ageSeconds === null || ageSeconds === undefined) return "Waiting for tick";
  if (ageSeconds < 2) return "Updated now";
  if (ageSeconds < 60) return `Updated ${Math.round(ageSeconds)}s ago`;
  return `Updated ${Math.round(ageSeconds / 60)}m ago`;
}

function ageInSeconds(value) {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, (Date.now() - timestamp) / 1000);
}
