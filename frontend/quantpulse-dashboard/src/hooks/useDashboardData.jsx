import { useEffect, useMemo, useState } from "react";
import {
  liveMarketWebSocketUrl,
  loadDashboardBatches,
  loadIntelligenceBundle,
  loadLiveMarketSnapshot,
  loadLiveMarketStatus,
  startLiveMarketListener,
} from "./dashboardApi";
import { buildDemoDashboardData } from "./dashboardDemoData";
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
      autoDecision: null,
      aiScores: null,
      multiTimeframe: null,
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
      autoDecision: bundle?.autoDecision || null,
      aiScores: bundle?.aiScores || null,
      multiTimeframe: bundle?.multiTimeframe || null,
      tradeSetup: bundle?.tradeSetup || null,
      entryTrigger: bundle?.entryTrigger || null,
    },
    lastRefresh: new Date(),
  };
}

function mergeDashboardBatches(current, { overviewByKey }, symbols) {
  const paperTradeBundle = overviewByKey.paperTradeBundle || {};
  return {
    ...current,
    signalsBySymbol: Object.fromEntries(
      symbols.map((symbol) => [symbol, overviewByKey[`signal:${symbol}`] || current.signalsBySymbol[symbol] || null])
    ),
    watchlist: overviewByKey.watchlist || current.watchlist,
    pipeline: overviewByKey.pipeline || current.pipeline,
    performance: paperTradeBundle.performance || current.performance,
    openTrades: paperTradeBundle.openTrades?.records || current.openTrades,
    closedTrades: paperTradeBundle.closedTrades?.records || current.closedTrades,
    selected: {
      ...current.selected,
      risk: current.selected.risk || overviewByKey.riskBundle?.risk || null,
      autoDecision: current.selected.autoDecision || overviewByKey.riskBundle?.autoDecision || null,
    },
    lastRefresh: new Date(),
  };
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

export default function useDashboardData({ view, filters, auto, symbols, autoRefreshMs }) {
  const [tick, setTick] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(createInitialDashboardData);
  const [liveMarket, setLiveMarket] = useState({});
  const [liveStatus, setLiveStatus] = useState({});

  useEffect(() => {
    let socket;
    let closed = false;
    let reconnectTimer = null;
    let reconnectAttempts = 0;

    const connect = () => {
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
        try {
          socket?.close();
        } catch {
          // No-op.
        }
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
      reconnectTimer = window.setTimeout(connect, delay);
    };

    connect();

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
    const id = window.setInterval(refreshSnapshot, autoRefreshMs);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [autoRefreshMs, symbols]);

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
  }, [symbols]);

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

    pollLiveStatus();
    const id = window.setInterval(pollLiveStatus, 10000);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    let refreshTimer = null;

    async function load() {
      setLoading(true);
      setError("");

      try {
        const selectedBundle = await loadIntelligenceBundle({ view, signal: controller.signal });

        if (cancelled) {
          return;
        }

        if (!selectedBundle?.signal) {
          setData(buildDemoDashboardData(view, symbols));
          setError("Live backend unavailable; showing demo market data.");
          return;
        }

        setData(createSelectedBundleData(view, selectedBundle));
        const dashboardBatches = await loadDashboardBatches({ view, filters, auto, symbols, signal: controller.signal });

        if (cancelled) {
          return;
        }

        setData((current) => mergeDashboardBatches(current, dashboardBatches, symbols));
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
  const selectedSignal = withLiveMarketPrice(
    data.selected.signal || signalsBySymbol[view.symbol] || null,
    liveMarket[view.symbol]
  );
  const selectedDiagnostics = data.selected.diagnostics || null;
  const selectedCandles = data.selected.candles?.records || [];
  const selectedOrderflow = data.selected.orderflow?.records || [];
  const selectedSmc = data.selected.smc?.records || [];
  const selectedRisk = data.selected.risk || null;
  const selectedAI = data.selected.aiScores || null;
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
      risk: selectedRisk,
      aiScores: selectedAI,
      multiTimeframe: data.selected.multiTimeframe,
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
    selectedRisk,
    selectedAI,
    data.selected.multiTimeframe,
    data.selected.tradeSetup,
    data.selected.entryTrigger,
  ]);

  const marketSummary = useMemo(() => {
    const rows = signalRows.filter(Boolean);
    const buyCount = rows.filter((row) => row.type === "BUY").length;
    const sellCount = rows.filter((row) => row.type === "SELL").length;
    const waitCount = rows.filter((row) => row.type === "WAIT").length;
    const readyCount = watchlist?.summary?.ready ?? 0;
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
      openCount,
      priceChange,
      avgConfidence,
    };
  }, [signalRows, watchlist, openTrades.length, selectedDetail.priceChangePct]);

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
