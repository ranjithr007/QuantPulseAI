import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import "./styles.css";
import DashboardHeader from "./components/DashboardHeader";
import useDashboardData from "./hooks/useDashboardData";
import { loadAutomationSettings, saveAutomationEmergencyStop, saveAutomationSettings } from "./hooks/dashboardApi";

const AutoTradingPage = React.lazy(() => import("./pages/AutoTradingPage"));
const BacktestPage = React.lazy(() => import("./pages/BacktestPage"));
const CoinDetailsPage = React.lazy(() => import("./pages/CoinDetailsPage"));
const DashboardHomePage = React.lazy(() => import("./pages/DashboardHomePage"));
const MarketScanPage = React.lazy(() => import("./pages/MarketScanPage"));
const PnlPage = React.lazy(() => import("./pages/PnlPage"));
const RiskControlsPage = React.lazy(() => import("./pages/RiskControlsPage"));
const RotationPage = React.lazy(() => import("./pages/RotationPage"));
const RsRankingPage = React.lazy(() => import("./pages/RsRankingPage"));
const SignalsPage = React.lazy(() => import("./pages/SignalsPage"));
const StageAnalysisPage = React.lazy(() => import("./pages/StageAnalysisPage"));
const TradingDetailsPage = React.lazy(() => import("./pages/TradingDetailsPage"));

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"];
const TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"];
const MODES = ["scalp", "intraday", "swing", "position"];
const AUTO_REFRESH_MS = 30000;
const SECTION = "mx-auto w-full max-w-[1680px] px-4 sm:px-6 lg:px-8";
const AUTO_SETTINGS_KEY = "quantpulse:auto-settings";
const SCAN_FILTERS_KEY = "quantpulse:scan-filters";

const PAGES = [
  "dashboard",
  "market-scan",
  "signals",
  "trading-details",
  "coin-details",
  "risk-controls",
  "auto-trading",
  "pnl",
  "backtest",
  "rotation",
  "rs-ranking",
  "stage-analysis",
];

function normalizeView(view) {
  return {
    symbol: SYMBOLS.includes((view.symbol || "").toUpperCase()) ? view.symbol.toUpperCase() : "BTCUSDT",
    timeframe: TIMEFRAMES.includes(view.timeframe) ? view.timeframe : "1h",
    mode: MODES.includes(view.mode) ? view.mode : "intraday",
  };
}

function getViewFromLocation(pathname, search) {
  const params = new URLSearchParams(search);
  const diagnosticsMatch = pathname.match(/^\/signals\/([^/]+)\/diagnostics\/?$/i);
  const coinMatch = pathname.match(/^\/coins\/([^/]+)\/?$/i);
  const routeSymbol = diagnosticsMatch
    ? decodeURIComponent(diagnosticsMatch[1]).toUpperCase()
    : coinMatch
      ? decodeURIComponent(coinMatch[1]).toUpperCase()
      : params.get("symbol");

  return normalizeView({
    symbol: routeSymbol,
    timeframe: params.get("timeframe"),
    mode: params.get("mode"),
  });
}

function getPageFromPath(pathname) {
  const path = pathname.toLowerCase();
  if (path.startsWith("/coins/") || /^\/signals\/[^/]+\/diagnostics\/?$/i.test(pathname)) return "coin-details";
  if (path.startsWith("/dashboard")) return "dashboard";
  if (path.startsWith("/risk-controls")) return "risk-controls";
  if (path.startsWith("/auto-trading")) return "auto-trading";
  if (path.startsWith("/pnl")) return "pnl";
  if (path.startsWith("/backtest")) return "backtest";
  if (path.startsWith("/rotation")) return "rotation";
  if (path.startsWith("/rs-ranking")) return "rs-ranking";
  if (path.startsWith("/stage-analysis")) return "stage-analysis";
  if (path.startsWith("/signals")) return "signals";
  if (path.startsWith("/trading-details")) return "trading-details";
  if (path.startsWith("/market-scan")) return "market-scan";
  return "dashboard";
}

function buildPageUrl(page, view) {
  const nextView = normalizeView(view);
  const params = new URLSearchParams();
  params.set("timeframe", nextView.timeframe);
  params.set("mode", nextView.mode);

  if (page === "coin-details") {
    return `/coins/${nextView.symbol}?${params.toString()}`;
  }

  params.set("symbol", nextView.symbol);

  if (page === "dashboard") return `/dashboard?${params.toString()}`;
  if (page === "risk-controls") return `/risk-controls?${params.toString()}`;
  if (page === "auto-trading") return `/auto-trading?${params.toString()}`;
  if (page === "pnl") return `/pnl?${params.toString()}`;
  if (page === "backtest") return `/backtest?${params.toString()}`;
  if (page === "rotation") return `/rotation?${params.toString()}`;
  if (page === "rs-ranking") return `/rs-ranking?${params.toString()}`;
  if (page === "stage-analysis") return `/stage-analysis?${params.toString()}`;
  if (page === "signals") return `/signals?${params.toString()}`;
  if (page === "trading-details") return `/trading-details?${params.toString()}`;
  return `/market-scan?${params.toString()}`;
}

function App() {
  return (
    <BrowserRouter>
      <DashboardApp />
    </BrowserRouter>
  );
}

function DashboardApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const routeView = useMemo(() => getViewFromLocation(location.pathname, location.search), [location.pathname, location.search]);
  const activePage = getPageFromPath(location.pathname);
  const [view, setViewState] = useState(routeView);
  const [filters, setFilters] = useState(loadScanFilters);
  const [auto, setAuto] = useState(loadAutoSettings);
  const [automationHydrated, setAutomationHydrated] = useState(false);

  const {
    setTick,
    loading,
    error,
    liveStatus,
    lastRefresh,
    marketSummary,
    signalRows,
    watchlist,
    selectedDetail,
    activeTradePlan,
    autoDecision,
    openTrades,
    selectedPipeline,
    candleSeries,
    volumeSeries,
    selectedRisk,
    equitySeries,
    pnlBySymbol,
    pnlBySide,
    tradeHistory,
    openPositions,
    dailyPnl,
    weeklyPnl,
    monthlyPnl,
    realizedPnl,
    unrealizedPnl,
    maxDrawdown,
    winningTrades,
    losingTrades,
    winRate,
  } = useDashboardData({
    view,
    filters,
    auto,
    symbols: SYMBOLS,
    autoRefreshMs: AUTO_REFRESH_MS,
  });

  useEffect(() => {
    if (routeView.symbol !== view.symbol || routeView.timeframe !== view.timeframe || routeView.mode !== view.mode) {
      setViewState(routeView);
    }
  }, [routeView, view.symbol, view.timeframe, view.mode]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    loadAutomationSettings({ signal: controller.signal })
      .then((settings) => {
        if (!cancelled && settings) setAuto(normalizeAutoSettings(settings));
      })
      .catch(() => {
        // Local settings remain as an offline fallback.
      })
      .finally(() => {
        if (!cancelled) setAutomationHydrated(true);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    saveLocalValue(AUTO_SETTINGS_KEY, auto);
    if (!automationHydrated) return undefined;

    const controller = new AbortController();
    const id = window.setTimeout(() => {
      saveAutomationSettings({ settings: auto, signal: controller.signal }).catch(() => {
        // Keep the local policy and retry after the next user change.
      });
    }, 500);

    return () => {
      window.clearTimeout(id);
      controller.abort();
    };
  }, [auto, automationHydrated]);

  const handleEmergencyStop = useCallback((active) => {
    const nextActive = Boolean(active);
    setAuto((current) => ({
      ...current,
      emergencyStop: nextActive,
      enabled: false,
      locked: true,
    }));
    saveAutomationEmergencyStop({ active: nextActive })
      .then((settings) => {
        if (settings) setAuto(normalizeAutoSettings(settings));
      })
      .catch(() => {
        // The local fail-safe state remains active if persistence is unavailable.
      });
  }, []);

  useEffect(() => {
    saveLocalValue(SCAN_FILTERS_KEY, filters);
  }, [filters]);

  const getPageHref = useCallback((page, nextView = view) => buildPageUrl(page, nextView), [view]);

  const handlePageChange = useCallback(
    (page, nextView = view) => {
      if (PAGES.includes(page)) {
        navigate(buildPageUrl(page, nextView));
      }
    },
    [navigate, view]
  );

  const setView = useCallback(
    (update) => {
      const nextView = normalizeView(typeof update === "function" ? update(view) : update);
      setViewState(nextView);
      navigate(buildPageUrl(activePage, nextView));
    },
    [activePage, navigate, view]
  );

  return (
    <DashboardLayout
      activePage={activePage}
      onPageChange={handlePageChange}
      getPageHref={getPageHref}
      view={view}
      filters={filters}
      setView={setView}
      setFilters={setFilters}
      setTick={setTick}
      loading={loading}
      error={error}
      liveStatus={liveStatus}
      lastRefresh={lastRefresh}
      marketSummary={marketSummary}
      signalRows={signalRows}
      watchlist={watchlist}
      selectedDetail={selectedDetail}
      activeTradePlan={activeTradePlan}
      autoDecision={autoDecision}
      auto={auto}
      setAuto={setAuto}
      onEmergencyStop={handleEmergencyStop}
      openTrades={openTrades}
      selectedPipeline={selectedPipeline}
      candleSeries={candleSeries}
      volumeSeries={volumeSeries}
      selectedRisk={selectedRisk}
      equitySeries={equitySeries}
      pnlBySymbol={pnlBySymbol}
      pnlBySide={pnlBySide}
      tradeHistory={tradeHistory}
      openPositions={openPositions}
      dailyPnl={dailyPnl}
      weeklyPnl={weeklyPnl}
      monthlyPnl={monthlyPnl}
      realizedPnl={realizedPnl}
      unrealizedPnl={unrealizedPnl}
      maxDrawdown={maxDrawdown}
      winningTrades={winningTrades}
      losingTrades={losingTrades}
      winRate={winRate}
    />
  );
}

function DashboardLayout({
  activePage,
  onPageChange,
  getPageHref,
  view,
  filters,
  setView,
  setFilters,
  setTick,
  loading,
  error,
  liveStatus,
  lastRefresh,
  marketSummary,
  signalRows,
  watchlist,
  selectedDetail,
  activeTradePlan,
  autoDecision,
  auto,
  setAuto,
  onEmergencyStop,
  openTrades,
  selectedPipeline,
  candleSeries,
  volumeSeries,
  selectedRisk,
  equitySeries,
  pnlBySymbol,
  pnlBySide,
  tradeHistory,
  openPositions,
  dailyPnl,
  weeklyPnl,
  monthlyPnl,
  realizedPnl,
  unrealizedPnl,
  maxDrawdown,
  winningTrades,
  losingTrades,
  winRate,
}) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <DashboardHeader
        activePage={activePage}
        onPageChange={onPageChange}
        getPageHref={getPageHref}
        view={view}
        lastRefresh={lastRefresh}
        loading={loading}
        liveStatus={liveStatus}
        selectedDetail={selectedDetail}
        symbols={SYMBOLS}
        modes={MODES}
        timeframes={TIMEFRAMES}
        signalRows={signalRows}
        setView={setView}
        setTick={setTick}
      />

      <main className="space-y-6 pb-24 lg:ml-72 lg:pb-8">
        {error ? (
          <div className={`${SECTION} pt-4`}>
            <div className="rounded-lg border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
              {error}
            </div>
          </div>
        ) : null}

        <Suspense fallback={<RouteLoading />}>
          <Routes>
            <Route
              path="/dashboard"
              element={
                <DashboardHomePage
                  view={view}
                  marketSummary={marketSummary}
                  selectedDetail={selectedDetail}
                  activeTradePlan={activeTradePlan}
                  autoDecision={autoDecision}
                  liveStatus={liveStatus}
                  watchlist={watchlist}
                  openTrades={openTrades}
                  signalRows={signalRows}
                  candleSeries={candleSeries}
                  selectedRisk={selectedRisk}
                  onOpenSymbol={(symbol) => onPageChange("coin-details", { ...view, symbol })}
                />
              }
            />
            <Route
              path="/market-scan"
              element={
                <MarketScanPage
                  view={view}
                  marketSummary={marketSummary}
                  selectedDetail={selectedDetail}
                  activeTradePlan={activeTradePlan}
                  autoDecision={autoDecision}
                  liveStatus={liveStatus}
                  watchlist={watchlist}
                  openTrades={openTrades}
                  signalRows={signalRows}
                  onOpenSymbol={(symbol) => onPageChange("coin-details", { ...view, symbol })}
                  getSymbolHref={(symbol) => getPageHref("coin-details", { ...view, symbol })}
                />
              }
            />
            <Route
              path="/signals"
              element={
                <SignalsPage
                  view={view}
                  filters={filters}
                  setView={setView}
                  setFilters={setFilters}
                  signalRows={signalRows}
                  watchlist={watchlist}
                  liveStatus={liveStatus}
                  onOpenSignal={(symbol) => onPageChange("coin-details", { ...view, symbol })}
                  getSymbolHref={(symbol) => getPageHref("coin-details", { ...view, symbol })}
                />
              }
            />
            <Route
              path="/coins/:symbol"
              element={
                <CoinDetailsPage
                  view={view}
                  selectedDetail={selectedDetail}
                  activeTradePlan={activeTradePlan}
                  candleSeries={candleSeries}
                  volumeSeries={volumeSeries}
                  selectedRisk={selectedRisk}
                  liveStatus={liveStatus}
                />
              }
            />
            <Route
              path="/signals/:symbol/diagnostics"
              element={
                <CoinDetailsPage
                  view={view}
                  selectedDetail={selectedDetail}
                  activeTradePlan={activeTradePlan}
                  candleSeries={candleSeries}
                  volumeSeries={volumeSeries}
                  selectedRisk={selectedRisk}
                  liveStatus={liveStatus}
                />
              }
            />
            <Route
              path="/trading-details"
              element={
                <TradingDetailsPage
                  view={view}
                  symbols={SYMBOLS}
                  auto={auto}
                  setAuto={setAuto}
                  onEmergencyStop={onEmergencyStop}
                  autoDecision={autoDecision}
                  selectedDetail={selectedDetail}
                  openTrades={openTrades}
                  selectedPipeline={selectedPipeline}
                  loading={loading}
                  realizedPnl={realizedPnl}
                  unrealizedPnl={unrealizedPnl}
                  dailyPnl={dailyPnl}
                  weeklyPnl={weeklyPnl}
                  monthlyPnl={monthlyPnl}
                  maxDrawdown={maxDrawdown}
                  winningTrades={winningTrades}
                  losingTrades={losingTrades}
                  winRate={winRate}
                  tradeHistory={tradeHistory}
                  openPositions={openPositions}
                  pnlBySymbol={pnlBySymbol}
                  pnlBySide={pnlBySide}
                  equitySeries={equitySeries}
                />
              }
            />
            <Route
              path="/risk-controls"
              element={
                <RiskControlsPage
                  view={view}
                  auto={auto}
                  setAuto={setAuto}
                  onEmergencyStop={onEmergencyStop}
                  autoDecision={autoDecision}
                  selectedDetail={selectedDetail}
                  selectedRisk={selectedRisk}
                  openTrades={openTrades}
                />
              }
            />
            <Route
              path="/auto-trading"
              element={
                <AutoTradingPage
                  view={view}
                  symbols={SYMBOLS}
                  auto={auto}
                  setAuto={setAuto}
                  onEmergencyStop={onEmergencyStop}
                  autoDecision={autoDecision}
                  selectedDetail={selectedDetail}
                  openTrades={openTrades}
                />
              }
            />
            <Route
              path="/pnl"
              element={
                <PnlPage
                  realizedPnl={realizedPnl}
                  unrealizedPnl={unrealizedPnl}
                  dailyPnl={dailyPnl}
                  weeklyPnl={weeklyPnl}
                  monthlyPnl={monthlyPnl}
                  maxDrawdown={maxDrawdown}
                  winningTrades={winningTrades}
                  losingTrades={losingTrades}
                  winRate={winRate}
                  tradeHistory={tradeHistory}
                  openPositions={openPositions}
                  pnlBySymbol={pnlBySymbol}
                  pnlBySide={pnlBySide}
                  equitySeries={equitySeries}
                />
              }
            />
            <Route
              path="/backtest"
              element={
                <BacktestPage
                  view={view}
                  selectedDetail={selectedDetail}
                  tradeHistory={tradeHistory}
                  equitySeries={equitySeries}
                  pnlBySymbol={pnlBySymbol}
                  dailyPnl={dailyPnl}
                  weeklyPnl={weeklyPnl}
                  monthlyPnl={monthlyPnl}
                  maxDrawdown={maxDrawdown}
                  winningTrades={winningTrades}
                  losingTrades={losingTrades}
                  winRate={winRate}
                />
              }
            />
            <Route
              path="/rotation"
              element={
                <RotationPage
                  signalRows={signalRows}
                  watchlist={watchlist}
                  getSymbolHref={(symbol) => getPageHref("coin-details", { ...view, symbol })}
                />
              }
            />
            <Route
              path="/rs-ranking"
              element={
                <RsRankingPage
                  signalRows={signalRows}
                  watchlist={watchlist}
                  activeSymbol={view.symbol}
                  getSymbolHref={(symbol) => getPageHref("coin-details", { ...view, symbol })}
                />
              }
            />
            <Route
              path="/stage-analysis"
              element={
                <StageAnalysisPage
                  signalRows={signalRows}
                  watchlist={watchlist}
                  activeSymbol={view.symbol}
                  getSymbolHref={(symbol) => getPageHref("coin-details", { ...view, symbol })}
                />
              }
            />
            <Route path="/" element={<Navigate to={buildPageUrl("dashboard", view)} replace />} />
            <Route path="*" element={<Navigate to={buildPageUrl("dashboard", view)} replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}

function RouteLoading() {
  return (
    <div className={`${SECTION} py-8`}>
      <div className="rounded-lg border border-white/10 bg-slate-900/70 p-4 text-sm text-slate-400">
        Loading page...
      </div>
    </div>
  );
}

const rootElement = document.getElementById("root");
const reactRoot = globalThis.__QUANTPULSE_REACT_ROOT__ || createRoot(rootElement);
globalThis.__QUANTPULSE_REACT_ROOT__ = reactRoot;
reactRoot.render(<App />);

function loadAutoSettings() {
  return normalizeAutoSettings(readLocalValue(AUTO_SETTINGS_KEY, null));
}

function loadScanFilters() {
  return normalizeScanFilters(readLocalValue(SCAN_FILTERS_KEY, null));
}

function normalizeAutoSettings(value) {
  const defaults = {
    enabled: false,
    locked: true,
    emergencyStop: false,
    allowedSymbols: ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"],
    maxRiskPerTrade: 1.0,
    dailyLossLimit: 4.0,
    maxOpenTrades: 4,
    maxLeverage: 5,
    maxPositionSize: 25000,
    minConfidence: 70,
    direction: "BOTH",
    executionMode: "PAPER",
    liveExecutionEnabled: false,
    version: 0,
  };

  if (!value || typeof value !== "object") {
    return defaults;
  }

  const allowedSymbols = Array.isArray(value.allowedSymbols)
    ? value.allowedSymbols.map((symbol) => String(symbol || "").toUpperCase()).filter((symbol) => SYMBOLS.includes(symbol))
    : defaults.allowedSymbols;

  const direction = String(value.direction || defaults.direction).toUpperCase();

  return {
    ...defaults,
    ...value,
    allowedSymbols,
    enabled: Boolean(value.enabled),
    locked: Boolean(value.locked),
    emergencyStop: Boolean(value.emergencyStop),
    maxRiskPerTrade: Number(value.maxRiskPerTrade) || defaults.maxRiskPerTrade,
    dailyLossLimit: Number(value.dailyLossLimit) || defaults.dailyLossLimit,
    maxOpenTrades: Number(value.maxOpenTrades) || defaults.maxOpenTrades,
    maxLeverage: Number(value.maxLeverage) || defaults.maxLeverage,
    maxPositionSize: Number(value.maxPositionSize) || defaults.maxPositionSize,
    minConfidence: Number(value.minConfidence) || defaults.minConfidence,
    direction: ["LONG", "SHORT", "BOTH"].includes(direction) ? direction : defaults.direction,
    executionMode: "PAPER",
    liveExecutionEnabled: false,
    version: Number(value.version) || defaults.version,
  };
}

function normalizeScanFilters(value) {
  const defaults = {
    watchlistStatus: "ALL",
    watchlistSide: "ALL",
    failedMax: "2",
  };

  if (!value || typeof value !== "object") {
    return defaults;
  }

  const watchlistStatus = String(value.watchlistStatus || defaults.watchlistStatus).toUpperCase();
  const watchlistSide = String(value.watchlistSide || defaults.watchlistSide).toUpperCase();
  const failedMax = String(value.failedMax ?? defaults.failedMax);

  return {
    watchlistStatus: ["ALL", "READY", "WAIT"].includes(watchlistStatus) ? watchlistStatus : defaults.watchlistStatus,
    watchlistSide: ["ALL", "LONG", "SHORT"].includes(watchlistSide) ? watchlistSide : defaults.watchlistSide,
    failedMax: ["0", "1", "2", "3", "4"].includes(failedMax) ? failedMax : defaults.failedMax,
  };
}

function readLocalValue(key, fallback) {
  if (typeof window === "undefined") return fallback;

  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function saveLocalValue(key, value) {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore quota and privacy-mode failures.
  }
}
