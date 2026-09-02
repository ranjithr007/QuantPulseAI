const API_BASE = import.meta.env.PROD
  ? new URL("/api/", window.location.origin).toString()
  : import.meta.env.VITE_BACKEND_URL || "http://127.0.0.1:8000";

function apiUrl(path) {
  return new URL(String(path).replace(/^\/+/, ""), API_BASE);
}
const STALE_AFTER_BY_TIMEFRAME = {
  "1m": 5 * 60,
  "5m": 15 * 60,
  "15m": 25 * 60,
  "1h": 65 * 60,
  "2h": (2 * 60 + 5) * 60,
  "4h": (4 * 60 + 5) * 60,
  "1d": (24 * 60 + 25) * 60,
};
const PAGE_DATA_NEEDS = {
  dashboard: { watchlist: true, paper: true, risk: true, signals: true },
  "market-scan": { watchlist: true, paper: true, risk: true, signals: true },
  signals: { watchlist: true, paper: true, signals: true },
  "market-trend": { signals: true },
  "market-move": { signals: true },
  "coin-pulse": { signals: true },
  strategies: { signals: true },
  "coin-details": { signals: true },
  "risk-controls": { paper: true, risk: true, signals: true },
  "auto-trading": { paper: true, risk: true, signals: true },
  pnl: { paper: true, signals: true },
  backtest: { signals: true },
  rotation: { watchlist: true, signals: true },
  "rs-ranking": { watchlist: true, signals: true },
  "stage-analysis": { watchlist: true, signals: true },
};
const SYMBOL_SCOPED_PAPER_PAGES = new Set([
  "risk-controls",
  "auto-trading",
]);

export function liveMarketWebSocketUrl(symbols = []) {
  const url = apiUrl("/ws/live-market");
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";

  if (symbols.length) {
    url.searchParams.set("symbols", symbols.join(","));
  }

  return url.toString();
}

export async function loadLiveMarketSnapshot({ symbols = [], signal }) {
  const response = await requestJson(
    "/live/market-snapshot",
    {
      symbols: symbols.join(","),
    },
    signal,
    20000
  );

  // LiveMarketResponse guarantees a records array, including empty/stale states.
  return response.records;
}

export async function loadLiveMarketStatus({ signal } = {}) {
  const response = await requestJson("/live/status", {}, signal);
  return response || null;
}

export async function loadMarketParticipationTrends({ signal } = {}) {
  const response = await requestJson("/market-participation/trends", {}, signal, 20000);
  return response || { source: "market_participation_trends", count: 0, records: [] };
}

export async function loadStrategySummary({ strategyId, sinceDays = 30, signal } = {}) {
  const response = await requestJson(
    "/strategies/summary",
    {
      strategy_id: strategyId,
      since_days: sinceDays,
      candidate_limit: 24,
    },
    signal,
    45000
  );
  return response || { source: "strategy_performance_v1", status: "UNAVAILABLE", records: [] };
}

export async function loadNotifications({ unreadOnly = false, limit = 50, signal } = {}) {
  return requestJson(
    "/notifications",
    { unread_only: unreadOnly, limit },
    signal,
    15000
  );
}

export async function markNotificationRead(notificationId, { signal } = {}) {
  return requestJson(
    `/notifications/${encodeURIComponent(notificationId)}/read`,
    {},
    signal,
    15000,
    "PATCH"
  );
}

export async function markAllNotificationsRead({ signal } = {}) {
  return requestJson(
    "/notifications/read-all",
    {},
    signal,
    15000,
    "POST"
  );
}

export async function startLiveMarketListener({ symbols = [], signal }) {
  const response = await requestJson(
    "/live/start",
    {
      symbols: symbols.join(","),
    },
    signal,
    60000,
    "POST"
  );

  return response || null;
}

export async function loadIntelligenceBundle({ view, signal }) {
  const response = await requestJson(
    `/intelligence/${view.symbol}/bundle`,
    {
      timeframe: view.timeframe,
      mode: view.mode,
      stale_after_seconds: staleAfterSeconds(view.timeframe),
    },
    signal,
    20000
  );

  return response || null;
}

export async function loadRiskBundle({ view, auto, signal }) {
  const response = await requestJson(
    `/risk/${view.symbol}/bundle`,
    {
      timeframe: view.timeframe,
      mode: view.mode,
      stale_after_seconds: staleAfterSeconds(view.timeframe),
      enabled: auto.enabled,
      locked: auto.locked,
      emergency_stop: auto.emergencyStop,
      allowed_symbols: auto.allowedSymbols?.join(",") || "",
      max_risk_per_trade: auto.maxRiskPerTrade,
      daily_loss_limit: auto.dailyLossLimit,
      max_open_trades: auto.maxOpenTrades,
      max_leverage: auto.maxLeverage,
      max_position_size: auto.maxPositionSize,
      min_confidence: auto.minConfidence,
      direction: auto.direction,
    },
    signal
  );

  return response || null;
}

export async function loadBacktestSummary({ symbol, signalSide, timeframe = "1h", signal }) {
  const response = await requestJson(
    "/backtest/filtered-summary",
    {
      symbol,
      signal: signalSide,
      timeframe,
    },
    signal
  );

  return response || null;
}

export async function loadWalkForwardSummary({ symbol, signalSide, timeframe = "1h", signal }) {
  const job = await requestJson(
    "/backtest/walk-forward/jobs",
    {
      symbol,
      signal: signalSide,
      timeframe,
      min_train_trades: 1,
    },
    signal,
    20000,
    "POST"
  );

  if (!job?.job_id) {
    throw new Error("Walk-forward job submission did not return a job id");
  }

  return pollWalkForwardJob(job.job_id, signal);
}

export async function loadPaperTradeMeasurement({ symbol, signal } = {}) {
  const response = await requestJson(
    "/paper-trade/measurement",
    { symbol },
    signal,
    30000
  );

  return response || null;
}

export async function loadPaperTradeOpportunities({ symbol, sinceHours = 24, signal } = {}) {
  const response = await requestJson(
    "/paper-trade/opportunities",
    {
      symbol,
      since_hours: sinceHours,
    },
    signal,
    30000
  );

  return response || null;
}

export async function loadPaperTradeLifecycleFunnel({ symbol, sinceHours = 24, signal } = {}) {
  const response = await requestJson(
    "/paper-trade/lifecycle-funnel",
    {
      symbol,
      since_hours: sinceHours,
    },
    signal,
    30000
  );

  return response || null;
}

export async function loadPhase2RollingValidation({ symbol, signal } = {}) {
  const response = await requestJson(
    "/paper-trade/rolling-validation",
    { symbol },
    signal,
    30000
  );

  return response || null;
}

export async function loadPaperTradeRecoveryEvents({ limit = 20, signal } = {}) {
  const response = await requestJson(
    "/paper-trade/recovery-events",
    { limit },
    signal,
    30000
  );

  return response || null;
}

export async function loadPhase2EvidenceCheckpoints({ limit = 30, signal } = {}) {
  const response = await requestJson(
    "/paper-trade/evidence-checkpoints",
    { limit },
    signal,
    30000
  );

  return response || null;
}

export async function loadPhase2ValidationReport({ symbol, signalSide, timeframe = "1h", signal }) {
  const response = await requestJson(
    "/backtest/phase2-report",
    {
      symbol,
      signal: signalSide,
      timeframe,
      min_train_trades: 1,
    },
    signal,
    120000
  );

  return response || null;
}

export async function exportPhase2ValidationReport({ symbol, signalSide, timeframe = "1h", validation, signal }) {
  const response = await requestJson(
    "/backtest/phase2-report/export",
    {
      symbol,
      signal: signalSide,
      timeframe,
      min_train_trades: 1,
    },
    signal,
    120000,
    "POST",
    { result: validation?.result || null }
  );

  return response || null;
}

export async function loadPhase2ValidationHistory({ symbol, timeframe, signalSide, limit = 8, signal } = {}) {
  const response = await requestJson(
    "/backtest/phase2-report/history",
    {
      symbol,
      timeframe,
      signal: signalSide,
      limit,
    },
    signal,
    30000
  );

  return response || null;
}

export async function loadPhase2ValidationArtifact({ artifactId, signal } = {}) {
  const response = await requestJson(
    "/backtest/phase2-report/artifact",
    {
      artifact_id: artifactId,
    },
    signal,
    30000
  );

  return response || null;
}

export async function loadPhase2ValidationSummary({ symbol, timeframe, signalSide, limit = 20, signal } = {}) {
  const response = await requestJson(
    "/backtest/phase2-report/summary",
    {
      symbol,
      timeframe,
      signal: signalSide,
      limit,
    },
    signal,
    30000
  );

  return response || null;
}

export async function loadAutomationSettings({ signal } = {}) {
  const response = await requestJson("/automation/settings", {}, signal, 15000);
  // AutomationEnvelope keeps settings explicit on success and null on failure.
  return response.settings;
}

export async function saveAutomationSettings({ settings, signal } = {}) {
  const response = await requestJson("/automation/settings", {}, signal, 15000, "PUT", settings);
  return response.settings;
}

export async function saveAutomationEmergencyStop({ active, signal } = {}) {
  const response = await requestJson("/automation/emergency-stop", {}, signal, 15000, "POST", { active: Boolean(active) });
  return response.settings;
}

export async function executePaperTradeCandidates({ symbol, staleAfterSeconds = 900, signal } = {}) {
  const response = await requestJson(
    "/paper-trade/execute-candidates",
    {
      symbol,
      stale_after_seconds: staleAfterSeconds,
    },
    signal,
    60000,
    "POST"
  );
  return response || null;
}

export async function persistReadyWatchlistSetups({ mode, side, staleAfterSeconds = 900, signal } = {}) {
  const response = await requestJson(
    "/signals/watchlist/persist-ready",
    {
      mode,
      side,
      stale_after_seconds: staleAfterSeconds,
    },
    signal,
    60000,
    "POST"
  );

  return response || null;
}

export async function loadPaperTradeCandidates({ symbol, staleAfterSeconds = 900, signal } = {}) {
  const response = await requestJson(
    "/paper-trade/candidates",
    {
      symbol,
      stale_after_seconds: staleAfterSeconds,
    },
    signal,
    60000
  );
  return response || null;
}

export async function loadDashboardBatches({ activePage, view, filters, auto, symbols, signal }) {
  const common = {
    timeframe: view.timeframe,
    stale_after_seconds: staleAfterSeconds(view.timeframe),
  };
  const needs = PAGE_DATA_NEEDS[activePage] || PAGE_DATA_NEEDS.dashboard;
  const paperSymbol = SYMBOL_SCOPED_PAPER_PAGES.has(activePage) ? view.symbol : null;
  const applyServerWatchlistFilters = activePage !== "signals";

  const overviewRequests = [];

  if (needs.watchlist) {
    overviewRequests.push({
      key: "watchlist",
      promise: requestJson(
        "/signals/watchlist",
        {
          mode: view.mode,
          stale_after_seconds: staleAfterSeconds(view.timeframe),
          status: applyServerWatchlistFilters && filters.watchlistStatus !== "ALL" ? filters.watchlistStatus : null,
          side: applyServerWatchlistFilters && filters.watchlistSide !== "ALL" ? filters.watchlistSide : null,
          failed_max: applyServerWatchlistFilters ? filters.failedMax : null,
        },
        signal
      ),
    });
  }

  if (needs.pipeline) {
    overviewRequests.push({
      key: "pipeline",
      promise: requestJson(
        "/pipeline/status",
        {
          mode: view.mode,
        },
        signal
      ),
    });
  }

  if (needs.paper) {
    overviewRequests.push({
      key: "paperTradeBundle",
      promise: requestJson(
        "/paper-trade/bundle",
        {
          symbol: paperSymbol,
          include_all: activePage === "pnl" ? true : null,
        },
        signal
      ),
    });
    overviewRequests.push({
      key: "paperTradeCandidates",
      promise: loadPaperTradeCandidates({
        symbol: paperSymbol,
        staleAfterSeconds: staleAfterSeconds(view.timeframe),
        signal,
      }),
    });
  }

  if (needs.risk) {
    overviewRequests.push({
      key: "riskBundle",
      promise: loadRiskBundle({ view, auto, signal }),
    });
  }

  if (needs.signals) {
    overviewRequests.push({
      key: "signalBatch",
      promise: requestJson(
        "/signals/batch",
        {
          ...common,
          symbols: symbols.join(","),
        },
        signal
      ),
    });
  }

  const [overviewByKey] = await Promise.all([resolveBatch(overviewRequests)]);

  return {
    overviewByKey,
  };
}

function staleAfterSeconds(timeframe) {
  return STALE_AFTER_BY_TIMEFRAME[String(timeframe || "").toLowerCase()] || 15 * 60;
}

async function resolveBatch(requests) {
  const settled = await Promise.allSettled(requests.map((item) => item.promise));
  return Object.fromEntries(
    requests.map((item, index) => [
      item.key,
      settled[index].status === "fulfilled" ? settled[index].value : null,
    ])
  );
}

async function requestJson(path, params = {}, signal, timeoutMs = 60000, method = "GET", body) {
  const url = apiUrl(path);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "" && value !== "ALL") {
      url.searchParams.set(key, String(value));
    }
  });

  const controller = new AbortController();
  let requestTimedOut = false;
  const timeoutId = window.setTimeout(() => {
    requestTimedOut = true;
    controller.abort();
  }, timeoutMs);

  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
  }

  let response;
  try {
    response = await fetch(url, {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (requestError) {
    if (requestTimedOut && requestError?.name === "AbortError") {
      throw new Error(`${url.pathname} timed out after ${Math.round(timeoutMs / 1000)} seconds`);
    }
    throw requestError;
  } finally {
    window.clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    if (response.status === 401) {
      window.dispatchEvent(new Event("quantpulse:unauthorized"));
    }
    throw new Error(`${url.pathname} returned ${response.status}${text ? ` - ${text}` : ""}`);
  }

  return response.json();
}

async function pollWalkForwardJob(jobId, signal) {
  const deadline = Date.now() + 15 * 60 * 1000;

  while (Date.now() < deadline) {
    const job = await requestJson(
      `/backtest/walk-forward/jobs/${encodeURIComponent(jobId)}`,
      {},
      signal,
      20000
    );

    if (job?.status === "COMPLETED") {
      if (!job.response) {
        throw new Error("Walk-forward job completed without a response");
      }
      return job.response;
    }
    if (job?.status === "FAILED") {
      throw new Error(job.error || "Walk-forward validation failed");
    }

    await abortableDelay(2000, signal);
  }

  throw new Error("Walk-forward validation is still running after 15 minutes");
}

function abortableDelay(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The operation was aborted", "AbortError"));
      return;
    }

    const timeoutId = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timeoutId);
        reject(new DOMException("The operation was aborted", "AbortError"));
      },
      { once: true }
    );
  });
}
