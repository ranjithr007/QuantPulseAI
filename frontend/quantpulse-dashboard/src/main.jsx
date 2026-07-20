import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import "./styles.css";
import DashboardHeader from "./components/DashboardHeader";
import useDashboardData from "./hooks/useDashboardData";
import { executePaperTradeCandidates, loadAutomationSettings, persistReadyWatchlistSetups, saveAutomationEmergencyStop, saveAutomationSettings } from "./hooks/dashboardApi";

const importAutoTradingPage = () => import("./pages/AutoTradingPage");
const importBacktestPage = () => import("./pages/BacktestPage");
const importCoinDetailsPage = () => import("./pages/CoinDetailsPage");
const importDashboardHomePage = () => import("./pages/DashboardHomePage");
const importMarketScanPage = () => import("./pages/MarketScanPage");
const importPnlPage = () => import("./pages/PnlPage");
const importRiskControlsPage = () => import("./pages/RiskControlsPage");
const importRotationPage = () => import("./pages/RotationPage");
const importRsRankingPage = () => import("./pages/RsRankingPage");
const importSignalsPage = () => import("./pages/SignalsPage");
const importStageAnalysisPage = () => import("./pages/StageAnalysisPage");
const importTradingDetailsPage = () => import("./pages/TradingDetailsPage");

const AutoTradingPage = React.lazy(importAutoTradingPage);
const BacktestPage = React.lazy(importBacktestPage);
const CoinDetailsPage = React.lazy(importCoinDetailsPage);
const DashboardHomePage = React.lazy(importDashboardHomePage);
const MarketScanPage = React.lazy(importMarketScanPage);
const PnlPage = React.lazy(importPnlPage);
const RiskControlsPage = React.lazy(importRiskControlsPage);
const RotationPage = React.lazy(importRotationPage);
const RsRankingPage = React.lazy(importRsRankingPage);
const SignalsPage = React.lazy(importSignalsPage);
const StageAnalysisPage = React.lazy(importStageAnalysisPage);
const TradingDetailsPage = React.lazy(importTradingDetailsPage);

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"];
// Entry scanning and active trading decisions use the higher-timeframe stack.
// Lower timeframes remain supported by backend diagnostics/history, but are not
// offered as active dashboard scan choices.
const TIMEFRAMES = ["1h", "4h", "1d"];
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

const ROUTE_PRELOADERS = [
  importDashboardHomePage,
  importMarketScanPage,
  importSignalsPage,
  importCoinDetailsPage,
  importTradingDetailsPage,
  importRiskControlsPage,
  importAutoTradingPage,
  importPnlPage,
  importBacktestPage,
  importRotationPage,
  importRsRankingPage,
  importStageAnalysisPage,
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
  const contractMatch = pathname.match(/^\/contracts\/([^/]+)\/?$/i);
  const routeSymbol = diagnosticsMatch
    ? decodeURIComponent(diagnosticsMatch[1]).toUpperCase()
    : contractMatch
      ? decodeURIComponent(contractMatch[1]).toUpperCase()
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
  if (path.startsWith("/coins/") || path.startsWith("/contracts/") || /^\/signals\/[^/]+\/diagnostics\/?$/i.test(pathname)) return "coin-details";
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
    return `/contracts/${nextView.symbol}?${params.toString()}`;
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
    selectedPaperTradeCandidate,
    paperTradeCandidates,
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
    activePage,
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
    const warmRoutes = () => {
      ROUTE_PRELOADERS.forEach((loadPage) => {
        loadPage().catch(() => {
          // Keep route loading resilient even if a prefetch fails.
        });
      });
    };

    if (typeof window.requestIdleCallback === "function") {
      const id = window.requestIdleCallback(warmRoutes, { timeout: 1500 });
      return () => window.cancelIdleCallback?.(id);
    }

    const id = window.setTimeout(warmRoutes, 250);
    return () => window.clearTimeout(id);
  }, []);

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

  const handleExecutePaperTrades = useCallback(() => {
    const controller = new AbortController();
    const normalizedSide =
      selectedDetail?.signalType === "BUY"
        ? "LONG"
        : selectedDetail?.signalType === "SELL"
          ? "SHORT"
          : undefined;

    persistReadyWatchlistSetups({
      mode: view.mode,
      side: normalizedSide,
      signal: controller.signal,
    })
      .catch(() => null)
      .then(() =>
        executePaperTradeCandidates({ symbol: view.symbol, signal: controller.signal })
      )
      .then(() => {
        setTick((current) => current + 1);
      })
      .catch(() => {
        // Keep the dashboard usable; the next scheduler cycle can refresh the trade state.
      });

    return () => controller.abort();
  }, [setTick, view.mode, view.symbol, selectedDetail?.signalType]);

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
      onExecutePaperTrades={handleExecutePaperTrades}
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
  onExecutePaperTrades,
  openTrades,
  selectedPipeline,
  candleSeries,
  volumeSeries,
  selectedRisk,
  selectedPaperTradeCandidate,
  paperTradeCandidates,
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
                  auto={auto}
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
                  selectedPaperTradeCandidate={selectedPaperTradeCandidate}
                  onOpenSymbol={(symbol) => onPageChange("coin-details", { ...view, symbol })}
                />
              }
            />
            <Route
              path="/market-scan"
              element={
                <MarketScanPage
                  view={view}
                  auto={auto}
                  filters={filters}
                  setFilters={setFilters}
                  marketSummary={marketSummary}
                  selectedDetail={selectedDetail}
                  activeTradePlan={activeTradePlan}
                  autoDecision={autoDecision}
                  liveStatus={liveStatus}
                  watchlist={watchlist}
                  selectedRisk={selectedRisk}
                  openTrades={openTrades}
                  signalRows={signalRows}
                  paperTradeCandidates={paperTradeCandidates}
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
                  auto={auto}
                  paperTradeCandidates={paperTradeCandidates}
                  onOpenSignal={(symbol) => onPageChange("coin-details", { ...view, symbol })}
                  getSymbolHref={(symbol) => getPageHref("coin-details", { ...view, symbol })}
                />
              }
            />
            <Route
              path="/contracts/:symbol"
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
                  selectedRisk={selectedRisk}
                  selectedPaperTradeCandidate={selectedPaperTradeCandidate}
                  onExecutePaperTrades={onExecutePaperTrades}
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
                  selectedPaperTradeCandidate={selectedPaperTradeCandidate}
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
                  selectedRisk={selectedRisk}
                  selectedPaperTradeCandidate={selectedPaperTradeCandidate}
                  openTrades={openTrades}
                  onExecutePaperTrades={onExecutePaperTrades}
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
                  selectedDetail={selectedDetail}
                  autoDecision={autoDecision}
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
                  auto={auto}
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
                  auto={auto}
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
                  auto={auto}
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
        Opening view...
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
    minConfidence: 65,
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
    executorStatus: "ALL",
  };

  if (!value || typeof value !== "object") {
    return defaults;
  }

  const watchlistStatus = String(value.watchlistStatus || defaults.watchlistStatus).toUpperCase();
  const watchlistSide = String(value.watchlistSide || defaults.watchlistSide).toUpperCase();
  const failedMax = String(value.failedMax ?? defaults.failedMax);
  const executorStatus = String(value.executorStatus || defaults.executorStatus).toUpperCase();

  return {
    watchlistStatus: ["ALL", "READY", "WAIT"].includes(watchlistStatus) ? watchlistStatus : defaults.watchlistStatus,
    watchlistSide: ["ALL", "LONG", "SHORT"].includes(watchlistSide) ? watchlistSide : defaults.watchlistSide,
    failedMax: ["0", "1", "2", "3", "4"].includes(failedMax) ? failedMax : defaults.failedMax,
    executorStatus: ["ALL", "READY", "BLOCKED", "NO_QUEUED_PLAN"].includes(executorStatus) ? executorStatus : defaults.executorStatus,
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
