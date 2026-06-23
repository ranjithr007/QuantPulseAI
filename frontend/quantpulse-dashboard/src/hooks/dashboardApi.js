const API_BASE = import.meta.env.VITE_BACKEND_URL || "http://127.0.0.1:8000";
const STALE_AFTER_BY_TIMEFRAME = {
  "1m": 5 * 60,
  "5m": 15 * 60,
  "15m": 25 * 60,
  "1h": 65 * 60,
  "4h": (4 * 60 + 5) * 60,
  "1d": (24 * 60 + 25) * 60,
};
const PAGE_DATA_NEEDS = {
  dashboard: { watchlist: true, paper: true, risk: true, signals: true },
  "market-scan": { watchlist: true, paper: true, risk: true, signals: true },
  signals: { watchlist: true, signals: true },
  "coin-details": {},
  "trading-details": { pipeline: true, paper: true, risk: true },
  "risk-controls": { paper: true, risk: true },
  "auto-trading": { paper: true, risk: true },
  pnl: { paper: true },
  backtest: { paper: true },
  rotation: { watchlist: true, signals: true },
  "rs-ranking": { watchlist: true, signals: true },
  "stage-analysis": { watchlist: true, signals: true },
};

export function liveMarketWebSocketUrl(symbols = []) {
  const url = new URL("/ws/live-market", API_BASE);
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

  return response?.records || [];
}

export async function loadLiveMarketStatus({ signal } = {}) {
  const response = await requestJson("/live/status", {}, signal);
  return response || null;
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

export async function loadBacktestSummary({ symbol, signalSide, timeframe = "15m", signal }) {
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

export async function loadAutomationSettings({ signal } = {}) {
  const response = await requestJson("/automation/settings", {}, signal, 15000);
  return response?.settings || null;
}

export async function saveAutomationSettings({ settings, signal } = {}) {
  const response = await requestJson("/automation/settings", {}, signal, 15000, "PUT", settings);
  return response?.settings || null;
}

export async function saveAutomationEmergencyStop({ active, signal } = {}) {
  const response = await requestJson("/automation/emergency-stop", {}, signal, 15000, "POST", { active: Boolean(active) });
  return response?.settings || null;
}

export async function loadDashboardBatches({ activePage, view, filters, auto, symbols, signal }) {
  const common = {
    timeframe: view.timeframe,
    stale_after_seconds: staleAfterSeconds(view.timeframe),
  };
  const needs = PAGE_DATA_NEEDS[activePage] || PAGE_DATA_NEEDS.dashboard;

  const overviewRequests = [];

  if (needs.watchlist) {
    overviewRequests.push({
      key: "watchlist",
      promise: requestJson(
        "/signals/watchlist",
        {
          mode: view.mode,
          status: filters.watchlistStatus === "ALL" ? null : filters.watchlistStatus,
          side: filters.watchlistSide === "ALL" ? null : filters.watchlistSide,
          failed_max: filters.failedMax,
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
      promise: requestJson("/paper-trade/bundle", {}, signal),
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
  const url = new URL(path, API_BASE);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "" && value !== "ALL") {
      url.searchParams.set(key, String(value));
    }
  });

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

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
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`${url.pathname} returned ${response.status}${text ? ` - ${text}` : ""}`);
  }

  return response.json();
}
