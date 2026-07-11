import { useEffect, useMemo, useState } from "react";
import {
  liveMarketWebSocketUrl,
  loadDashboardBatches,
  loadIntelligenceBundle,
  loadLiveMarketSnapshot,
  loadLiveMarketStatus,
  startLiveMarketListener,
} from "./dashboardApi";
import { deriveRowEligibilityState } from "../utils/eligibility";
import {
  buildEquityCurve,
  buildGroupPnL,
  buildSelectedDetail,
  buildSignalRow,
  calculateMaxDrawdown,
  dateValue,
  estimatePnlPercent,
  evaluateAutoTrading,
  normalizeCandles,
  safeNumber,
  sumPnl,
  sumWithinDays,
} from "./dashboardTransforms";

const LIVE_SNAPSHOT_REFRESH_MS = 10_000;

function createInitialDashboardData() {
  return {
    signalsBySymbol: {},
    watchlist: null,
    pipeline: null,
    performance: null,
    openTrades: [],
    closedTrades: [],
    selected: {
      signal: null,
      diagnostics: null,
      candles: null,
      orderflow: null,
      smc: null,
      risk: null,
      paperTradeCandidates: [],
      autoDecision: null,
      aiScores: null,
      derivatives: null,
      multiTimeframe: null,
      predictionContext: null,
      prediction: null,
      timing: null,
      tradeSetup: null,
      entryTrigger: null,
    },
    lastRefresh: null,
  };
}

function createSelectedBundleData(view, bundle) {
  return {
    signalsBySymbol: {
      [view.symbol]: bundle?.signal || null,
    },
    watchlist: null,
    pipeline: null,
    performance: null,
    openTrades: [],
    closedTrades: [],
    selected: {
      signal: bundle?.signal || null,
      diagnostics: bundle?.diagnostics || null,
      candles: bundle?.candles || null,
      orderflow: bundle?.orderflow || null,
      smc: bundle?.smc || null,
      risk: bundle?.risk || null,
      paperTradeCandidates: [],
      autoDecision: bundle?.autoDecision || null,
      aiScores: bundle?.aiScores || null,
      derivatives: bundle?.derivatives || null,
      multiTimeframe: bundle?.multiTimeframe || null,
      predictionContext: bundle?.predictionContext || bundle?.multiTimeframe || null,
      prediction: bundle?.prediction || bundle?.tradeSetup || null,
      timing: bundle?.timing || bundle?.entryTrigger || null,
      tradeSetup: bundle?.tradeSetup || null,
      entryTrigger: bundle?.entryTrigger || null,
    },
    lastRefresh: new Date(),
  };
}

function normalizeWatchlistPayload(watchlist) {
  if (!watchlist || typeof watchlist !== "object") {
    return watchlist;
  }

  const records = Array.isArray(watchlist.records) ? watchlist.records : [];
  const computedSummary = records.reduce(
    (acc, item) => {
      const status = String(item?.status || "").toUpperCase();
      const side = String(item?.side || "").toUpperCase();

      if (status === "READY") acc.ready += 1;
      if (status === "WAIT") acc.wait += 1;
      if (side === "LONG") acc.long += 1;
      if (side === "SHORT") acc.short += 1;
      if (!side) acc.no_side += 1;

      return acc;
    },
    { ready: 0, wait: 0, long: 0, short: 0, no_side: 0, total: records.length }
  );

  return {
    ...watchlist,
    records,
    count: records.length,
    total_count: records.length,
    summary: {
      ...(watchlist.summary || {}),
      ...computedSummary,
      total: records.length,
    },
  };
}

function mergeDashboardBatches(current, { overviewByKey }, symbols, view) {
  const paperTradeBundle = overviewByKey.paperTradeBundle || {};
  const signalBatch = overviewByKey.signalBatch?.records_by_symbol || {};
  return {
    ...current,
    signalsBySymbol: Object.fromEntries(
      symbols.map((symbol) => {
        if (signalBatch && Object.prototype.hasOwnProperty.call(signalBatch, symbol)) {
          return [symbol, signalBatch[symbol]];
        }

        return [symbol, current.signalsBySymbol[symbol] || null];
      })
    ),
    watchlist: normalizeWatchlistPayload(overviewByKey.watchlist || current.watchlist),
    pipeline: overviewByKey.pipeline || current.pipeline,
    performance: paperTradeBundle.performance || current.performance,
    openTrades: paperTradeBundle.openTrades?.records || current.openTrades,
    closedTrades: paperTradeBundle.closedTrades?.records || current.closedTrades,
    selected: {
      ...current.selected,
      signal:
        signalBatch && Object.prototype.hasOwnProperty.call(signalBatch, view.symbol)
          ? signalBatch[view.symbol]
          : matchesSelectedSignal(current.selected.signal, view)
            ? current.selected.signal
            : null,
      risk:
        overviewByKey.riskBundle?.computedRisk ||
        current.selected.risk ||
        overviewByKey.riskBundle?.risk ||
        null,
      paperTradeCandidates:
        overviewByKey.paperTradeCandidates?.records ||
        current.selected.paperTradeCandidates ||
        [],
      autoDecision: current.selected.autoDecision || overviewByKey.riskBundle?.autoDecision || null,
    },
    lastRefresh: new Date(),
  };
}

function normalizeTradeSide(value) {
  const side = String(value || "").toUpperCase();
  if (["BUY", "LONG", "STRONG_LONG"].includes(side)) return "LONG";
  if (["SELL", "SHORT", "STRONG_SHORT"].includes(side)) return "SHORT";
  return side || null;
}

function executorRowState(row, candidates = []) {
  const side = normalizeTradeSide(row?.type);
  const candidate = candidates.find(
    (item) =>
      String(item?.symbol || "").toUpperCase() === String(row?.symbol || "").toUpperCase() &&
      normalizeTradeSide(item?.side) === side
  );

  if (!candidate) return "no_queued_plan";
  return candidate.eligible ? "executor_ready" : "executor_blocked";
}

function withLiveMarketPrice(signal, liveRecord) {
  if (!liveRecord?.current_price) {
    return signal;
  }

  const receivedAt = Date.parse(liveRecord.received_at || liveRecord.event_time || "");
  const ageMs = Number.isFinite(receivedAt) ? Math.max(0, Date.now() - receivedAt) : Number.POSITIVE_INFINITY;
  const useLivePrice = ageMs <= 90_000;
  const baseSignal = signal || {
    source: "live_market_only",
    signal: "WAIT",
    bias: "WAIT",
    confidence: 0,
    reasons: ["Waiting for AI intelligence"],
  };

  return {
    ...baseSignal,
    current_price: useLivePrice ? liveRecord.current_price : baseSignal.current_price,
    live_market: liveRecord,
    live_price_applied: useLivePrice,
  };
}

export default function useDashboardData({ activePage, view, filters, auto, symbols, autoRefreshMs }) {
  const [tick, setTick] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(createInitialDashboardData);
  const [liveMarket, setLiveMarket] = useState({});
  const [liveStatus, setLiveStatus] = useState({});
  const [resumeTick, setResumeTick] = useState(0);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState !== "hidden") {
        setResumeTick((current) => current + 1);
      }
    };
    const handleWindowFocus = () => setResumeTick((current) => current + 1);

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", handleWindowFocus);
    window.addEventListener("pageshow", handleWindowFocus);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", handleWindowFocus);
      window.removeEventListener("pageshow", handleWindowFocus);
    };
  }, []);

  useEffect(() => {
    let socket;
    let closed = false;
    let reconnectTimer = null;
    let reconnectAttempts = 0;

    const connect = async () => {
      if (closed) return;

      try {
        await startLiveMarketListener({ symbols });
      } catch {
        // Keep going; websocket and snapshot fallbacks can still recover.
      }

      if (closed) return;

      try {
        socket = new WebSocket(liveMarketWebSocketUrl(symbols));
      } catch {
        scheduleReconnect();
        return;
      }

      socket.onopen = () => {
        reconnectAttempts = 0;
      };

      socket.onmessage = (event) => {
        if (closed) return;

        try {
          const message = JSON.parse(event.data);
          const records = message.records || (message.record ? [message.record] : []);

          if (!records.length) return;

          setLiveMarket((current) => {
            const next = { ...current };

            records.forEach((record) => {
              if (record?.symbol) {
                next[record.symbol] = record;
              }
            });

            return next;
          });
          setLiveStatus((current) => ({ ...current, running: true, connected: true, state: "LIVE" }));
        } catch {
          // Ignore malformed live ticks and keep the REST snapshot.
        }
      };

      socket.onerror = () => {
        // Let the browser surface the transport error and use onclose/reconnect.
        // Closing here can produce noisy "no close frame" errors on transient drops.
      };

      socket.onclose = () => {
        if (!closed) {
          scheduleReconnect();
        }
      };
    };

    const scheduleReconnect = () => {
      if (closed) return;

      const delay = Math.min(15000, 1000 * 2 ** reconnectAttempts);
      reconnectAttempts += 1;
      reconnectTimer = window.setTimeout(() => {
        void connect();
      }, delay);
    };

    void connect();

    return () => {
      closed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);

      if (socket && socket.readyState <= WebSocket.OPEN) {
        socket.close();
      }
    };
  }, [symbols]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function refreshSnapshot() {
      try {
        const records = await loadLiveMarketSnapshot({ symbols, signal: controller.signal });

        if (cancelled || !records.length) {
          return;
        }

        setLiveMarket((current) => {
          const next = { ...current };

          records.forEach((record) => {
            if (record?.symbol) {
              next[record.symbol] = record;
            }
          });

          return next;
        });
        setLiveStatus((current) => ({ ...current, running: true }));
      } catch {
        // Snapshot polling is a fallback, so keep the websocket or cached state if it fails.
      }
    }

    refreshSnapshot();
    const id = window.setInterval(refreshSnapshot, LIVE_SNAPSHOT_REFRESH_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [autoRefreshMs, symbols, resumeTick]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function ensureLiveFeed() {
      try {
        const status = await loadLiveMarketStatus({ signal: controller.signal });
        if (cancelled) return;

        setLiveStatus(status || {});

        if (!status?.running) {
          const started = await startLiveMarketListener({ symbols, signal: controller.signal });
          if (cancelled) return;
          if (started) {
            setLiveStatus(started || {});
          }
        }
      } catch {
        // If the live service cannot be reached we keep using the websocket/snapshot fallback.
      }
    }

    ensureLiveFeed();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [symbols, resumeTick]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function pollLiveStatus() {
      try {
        const status = await loadLiveMarketStatus({ signal: controller.signal });
        if (cancelled) return;
        setLiveStatus(status || {});
      } catch {
        // Keep the last known state and let the live feed retry logic continue.
      }
    }

    const id = window.setInterval(pollLiveStatus, LIVE_SNAPSHOT_REFRESH_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [resumeTick]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    let refreshTimer = null;

    async function load() {
      setLoading(true);
      setError("");

        try {
          if (pageNeedsSelectedBundle(activePage)) {
            try {
              const selectedBundle = await loadIntelligenceBundle({ view, signal: controller.signal });

            if (cancelled) {
              return;
            }

              if (selectedBundle?.signal) {
                setData(createSelectedBundleData(view, selectedBundle));
              }
            } catch {
              // Non-blocking: selected bundle can fall back to the live batch payload.
            }
          }

        const dashboardBatches = await loadDashboardBatches({ activePage, view, filters, auto, symbols, signal: controller.signal });

        if (cancelled) {
          return;
        }

        setData((current) => mergeDashboardBatches(current, dashboardBatches, symbols, view));
      } catch (exception) {
        if (!cancelled) {
          setError(exception instanceof Error ? exception.message : "Unable to load dashboard");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          refreshTimer = window.setTimeout(load, autoRefreshMs);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
      controller.abort();
      if (refreshTimer) window.clearTimeout(refreshTimer);
    };
  }, [
    view.symbol,
    view.timeframe,
    view.mode,
    activePage,
    auto.enabled,
    auto.locked,
    auto.emergencyStop,
    auto.allowedSymbols.join(","),
    auto.maxRiskPerTrade,
    auto.dailyLossLimit,
    auto.maxOpenTrades,
    auto.maxLeverage,
    auto.maxPositionSize,
    auto.minConfidence,
    auto.direction,
    filters.watchlistStatus,
    filters.watchlistSide,
    filters.failedMax,
    tick,
    symbols,
    resumeTick,
  ]);

  const signalsBySymbol = useMemo(
    () =>
      Object.fromEntries(
        symbols.map((symbol) => [
          symbol,
          withLiveMarketPrice(data.signalsBySymbol?.[symbol] || null, liveMarket[symbol]),
        ])
      ),
    [symbols, data.signalsBySymbol, liveMarket]
  );
  const selectedSourceSignal = matchesSelectedSignal(data.selected.signal, view)
    ? data.selected.signal
    : signalsBySymbol[view.symbol] || null;
  const selectedSignal = withLiveMarketPrice(
    selectedSourceSignal,
    liveMarket[view.symbol]
  );
  const selectedDiagnostics = data.selected.diagnostics || null;
  const selectedCandles = data.selected.candles?.records || [];
  const selectedOrderflow = data.selected.orderflow?.records || [];
  const selectedSmc = data.selected.smc?.records || [];
  const selectedOrderflowPayload = data.selected.orderflow || null;
  const selectedSmcPayload = data.selected.smc || null;
  const selectedRisk = data.selected.risk || null;
  const selectedAI = data.selected.aiScores || null;
  const selectedDerivatives = data.selected.derivatives || null;
  const selectedPaperTradeCandidates = data.selected.paperTradeCandidates || [];
  const selectedPipeline = data.pipeline || null;
  const watchlist = data.watchlist;
  const performance = data.performance || {};
  const openTrades = data.openTrades || [];
  const closedTrades = data.closedTrades || [];

  const signalRows = useMemo(() => {
    return symbols.map((symbol) => buildSignalRow(symbol, signalsBySymbol[symbol], watchlist));
  }, [symbols, signalsBySymbol, watchlist]);

  const selectedDetail = useMemo(() => {
    return buildSelectedDetail({
      symbol: view.symbol,
      timeframe: view.timeframe,
      signal: selectedSignal,
      diagnostics: selectedDiagnostics,
      candles: selectedCandles,
      orderflow: selectedOrderflow,
      smc: selectedSmc,
      orderflowPayload: selectedOrderflowPayload,
      smcPayload: selectedSmcPayload,
      risk: selectedRisk,
      aiScores: selectedAI,
      derivatives: selectedDerivatives,
      multiTimeframe: data.selected.multiTimeframe,
      predictionContext: data.selected.predictionContext,
      prediction: data.selected.prediction,
      timing: data.selected.timing,
      tradeSetup: data.selected.tradeSetup,
      entryTrigger: data.selected.entryTrigger,
    });
  }, [
    view.symbol,
    view.timeframe,
    selectedSignal,
    selectedDiagnostics,
    selectedCandles,
    selectedOrderflow,
    selectedSmc,
    selectedOrderflowPayload,
    selectedSmcPayload,
    selectedRisk,
    selectedAI,
    selectedDerivatives,
    data.selected.multiTimeframe,
    data.selected.predictionContext,
    data.selected.prediction,
    data.selected.timing,
    data.selected.tradeSetup,
    data.selected.entryTrigger,
  ]);
  const selectedPaperTradeCandidate = useMemo(() => {
    if (!selectedPaperTradeCandidates.length) {
      return null;
    }

    const symbolCandidates = selectedPaperTradeCandidates.filter(
      (candidate) => String(candidate?.symbol || "").toUpperCase() === String(view.symbol || "").toUpperCase()
    );
    if (!symbolCandidates.length) {
      return null;
    }

    const preferredSide = normalizeTradeSide(
      selectedRisk?.signal ||
      selectedDetail.signalType ||
      selectedSignal?.signal ||
      selectedSignal?.decision
    );

    return (
      symbolCandidates.find(
        (candidate) => normalizeTradeSide(candidate?.side) === preferredSide
      ) || symbolCandidates[0]
    );
  }, [
    view.symbol,
    selectedPaperTradeCandidates,
    selectedRisk?.signal,
    selectedDetail.signalType,
    selectedSignal?.signal,
    selectedSignal?.decision,
  ]);

  const marketSummary = useMemo(() => {
    const rows = signalRows.filter(Boolean);
    const rowStates = rows.map((row) => {
      const watchRow = (watchlist?.records || []).find((item) => item.symbol === row.symbol) || {};
      const risk = deriveRowEligibilityState({
        row,
        watchRow,
        minConfidence: auto.minConfidence,
      });
      return { row, risk };
    });
    const eligibleRows = rowStates.filter(({ risk }) => risk.label === "Eligible" || risk.label === "Ready to execute");
    const buyCount = rows.filter((row) => row.type === "BUY").length;
    const sellCount = rows.filter((row) => row.type === "SELL").length;
    const waitCount = rows.filter((row) => row.type === "WAIT").length;
    const readyCount = eligibleRows.length;
    const persistedReadyCount = eligibleRows.filter(({ risk }) => String(risk.note || "").startsWith("Persisted risk:")).length;
    const computedReadyCount = eligibleRows.filter(({ risk }) => String(risk.note || "").startsWith("Computed risk:")).length;
    const fallbackReadyCount = eligibleRows.filter(({ risk }) => String(risk.note || "").startsWith("Trigger fallback:")).length;
    const executorReadyCount = rows.filter((row) => executorRowState(row, selectedPaperTradeCandidates) === "executor_ready").length;
    const executorBlockedCount = rows.filter((row) => executorRowState(row, selectedPaperTradeCandidates) === "executor_blocked").length;
    const noQueuedPlanCount = rows.filter((row) => executorRowState(row, selectedPaperTradeCandidates) === "no_queued_plan").length;
    const openCount = openTrades.length;
    const priceChange = selectedDetail.priceChangePct ?? 0;
    const avgConfidence = rows.length
      ? rows.reduce((sum, row) => sum + (row.confidence || 0), 0) / rows.length
      : 0;

    return {
      buyCount,
      sellCount,
      waitCount,
      readyCount,
      persistedReadyCount,
      computedReadyCount,
      fallbackReadyCount,
      executorReadyCount,
      executorBlockedCount,
      noQueuedPlanCount,
      openCount,
      priceChange,
      avgConfidence,
    };
  }, [signalRows, watchlist, auto.minConfidence, selectedPaperTradeCandidates, openTrades.length, selectedDetail.priceChangePct]);

  const activeTradePlan = selectedDetail.tradePlan;
  const computedAutoDecision = useMemo(() => {
    return evaluateAutoTrading({
      auto,
      selectedSymbol: view.symbol,
      signal: selectedSignal,
      risk: selectedRisk,
      performance,
      openTrades,
      tradePlan: activeTradePlan,
      multiTimeframe: data.selected.multiTimeframe,
    });
  }, [auto, view.symbol, selectedSignal, selectedRisk, performance, openTrades, activeTradePlan, data.selected.multiTimeframe]);
  const autoDecision = data.selected.autoDecision || computedAutoDecision;

  const candleSeries = useMemo(() => normalizeCandles(selectedCandles), [selectedCandles]);
  const volumeSeries = useMemo(
    () =>
      candleSeries.map((candle) => ({
        time: candle.time,
        volume: candle.volume,
      })),
    [candleSeries]
  );
  const equitySeries = useMemo(() => buildEquityCurve(closedTrades), [closedTrades]);
  const pnlBySymbol = useMemo(() => buildGroupPnL(closedTrades, "symbol"), [closedTrades]);
  const pnlBySide = useMemo(() => buildGroupPnL(closedTrades, "side"), [closedTrades]);
  const tradeHistory = useMemo(() => {
    return [...closedTrades].sort((a, b) => dateValue(b.closed_at || b.created_at) - dateValue(a.closed_at || a.created_at));
  }, [closedTrades]);
  const openPositions = useMemo(() => {
    return openTrades
      .map((trade) => {
        const current = safeNumber(signalsBySymbol[trade.symbol]?.current_price, trade.entry_price);
        const pnl = estimatePnlPercent(trade.side, trade.entry_price, current);
        return {
          ...trade,
          current_price: current,
          unrealized_pnl_percent: pnl,
        };
      })
      .sort((a, b) => Math.abs(b.unrealized_pnl_percent || 0) - Math.abs(a.unrealized_pnl_percent || 0));
  }, [openTrades, signalsBySymbol]);

  const dailyPnl = sumWithinDays(closedTrades, 1);
  const weeklyPnl = sumWithinDays(closedTrades, 7);
  const monthlyPnl = sumWithinDays(closedTrades, 30);
  const realizedPnl = sumPnl(closedTrades);
  const unrealizedPnl = sumPnl(openPositions, "unrealized_pnl_percent");
  const maxDrawdown = calculateMaxDrawdown(equitySeries);
  const winningTrades = closedTrades.filter((trade) => safeNumber(trade.pnl_percent, 0) > 0).length;
  const losingTrades = closedTrades.filter((trade) => safeNumber(trade.pnl_percent, 0) < 0).length;
  const winRate = closedTrades.length ? (winningTrades / closedTrades.length) * 100 : 0;

  return {
    setTick,
    loading,
    error,
    liveStatus,
    lastRefresh: data.lastRefresh,
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
    paperTradeCandidates: selectedPaperTradeCandidates,
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
  };
}

function pageNeedsSelectedBundle(activePage) {
  return new Set([
    "dashboard",
    "market-scan",
    "coin-details",
    "derivatives",
    "trading-details",
    "risk-controls",
    "auto-trading",
    "pnl",
    "backtest",
  ]).has(activePage);
}

function matchesSelectedSignal(signal, view) {
  if (!signal) return false;

  return (
    String(signal.symbol || "").toUpperCase() === String(view.symbol || "").toUpperCase() &&
    String(signal.timeframe || "").toLowerCase() === String(view.timeframe || "").toLowerCase()
  );
}
