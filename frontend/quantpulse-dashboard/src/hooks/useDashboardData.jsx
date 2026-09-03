import { useEffect, useMemo, useRef, useState } from "react";
import {
  liveMarketWebSocketUrl,
  loadDashboardBatches,
  loadIntelligenceBundle,
  loadLiveMarketSnapshot,
  loadLiveMarketStatus,
  loadSignalBatch,
  startLiveMarketListener,
} from "./dashboardApi";
import { deriveRowEligibilityState } from "../utils/eligibility";
import { isCandidateExecutorReady, selectExecutorCandidate } from "../utils/executorCompetition";
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

const LIVE_SNAPSHOT_FALLBACK_MS = 30_000;
const LIVE_STATUS_FALLBACK_MS = 60_000;
const OFFICIAL_PAPER_ENTRY_TIMEFRAMES = new Set(["1h", "2h", "4h", "1d"]);

function createInitialDashboardData() {
  return {
    signalsBySymbol: {},
    watchlist: null,
    pipeline: null,
    performance: null,
    accountRisk: null,
    paperWallet: null,
    ledgerScope: null,
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

function preferCurrentComputedRisk(currentRisk, incomingRisk, view) {
  const normalizedSymbol = String(view?.symbol || "").trim().toUpperCase();
  const normalizedTimeframe = String(view?.timeframe || "").trim().toLowerCase();
  const normalizedMode = String(view?.mode || "").trim().toLowerCase();
  const currentSymbol = String(currentRisk?.symbol || "").trim().toUpperCase();
  const currentTimeframe = String(currentRisk?.timeframe || "").trim().toLowerCase();
  const currentMode = String(currentRisk?.mode || "").trim().toLowerCase();

  if (
    currentRisk?.source === "computed_current" &&
    currentSymbol === normalizedSymbol &&
    currentTimeframe === normalizedTimeframe &&
    currentMode === normalizedMode
  ) {
    return currentRisk;
  }

  return incomingRisk || null;
}

function mergeSelectedBundleData(current, view, bundle) {
  return {
    ...current,
    signalsBySymbol: {
      ...current.signalsBySymbol,
      [view.symbol]: bundle?.signal || null,
    },
    selected: {
      ...current.selected,
      signal: bundle?.signal || null,
      diagnostics: bundle?.diagnostics || null,
      candles: bundle?.candles || null,
      orderflow: bundle?.orderflow || null,
      smc: bundle?.smc || null,
      risk: preferCurrentComputedRisk(
        current.selected.risk,
        bundle?.risk,
        view
      ),
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
  const officialOpenTrades = scopePaperTrades(paperTradeBundle.openTrades?.records);
  const officialClosedTrades = scopePaperTrades(paperTradeBundle.closedTrades?.records);
  const officialPerformance = buildScopedPaperPerformance(
    paperTradeBundle.performance,
    officialOpenTrades,
    officialClosedTrades
  );
  const hasPaperTradePayload = Boolean(
    paperTradeBundle.openTrades || paperTradeBundle.closedTrades
  );
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
    performance: officialPerformance || current.performance,
    accountRisk: paperTradeBundle.accountRisk || current.accountRisk,
    paperWallet: paperTradeBundle.paperWallet || current.paperWallet,
    ledgerScope: paperTradeBundle.ledgerScope
      ? {
          ...paperTradeBundle.ledgerScope,
          symbol_filter: paperTradeBundle.symbol_filter ?? null,
        }
      : current.ledgerScope,
    openTrades: hasPaperTradePayload ? officialOpenTrades : current.openTrades,
    closedTrades: hasPaperTradePayload ? officialClosedTrades : current.closedTrades,
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
        overviewByKey.riskBundle?.risk ||
        current.selected.risk ||
        null,
      paperTradeCandidates:
        overviewByKey.paperTradeCandidates?.records ||
        current.selected.paperTradeCandidates ||
        [],
      autoDecision: overviewByKey.riskBundle?.autoDecision || current.selected.autoDecision || null,
    },
    lastRefresh: new Date(),
  };
}

function scopePaperTrades(records) {
  const seenIds = new Set();
  return (records || []).filter((trade) => {
    if (String(trade?.symbol || "").trim().toUpperCase().startsWith("QA")) {
      return false;
    }
    if (!OFFICIAL_PAPER_ENTRY_TIMEFRAMES.has(String(trade?.entry_timeframe || "").trim())) {
      return false;
    }

    const id = trade?.id;
    if (id === null || id === undefined) return true;
    const identity = String(id);
    if (seenIds.has(identity)) return false;
    seenIds.add(identity);
    return true;
  });
}

function mergeSignalBatchData(current, signalBatch, symbols, view) {
  const records = signalBatch?.records_by_symbol || {};
  return {
    ...current,
    signalsBySymbol: Object.fromEntries(
      symbols.map((symbol) => [
        symbol,
        Object.prototype.hasOwnProperty.call(records, symbol)
          ? records[symbol]
          : current.signalsBySymbol[symbol] || null,
      ])
    ),
    selected: {
      ...current.selected,
      signal: Object.prototype.hasOwnProperty.call(records, view.symbol)
        ? records[view.symbol]
        : current.selected.signal,
    },
    lastRefresh: new Date(),
  };
}

function requestErrorMessage(error, fallback) {
  return error instanceof Error ? error.message : fallback;
}

function buildScopedPaperPerformance(performance, openTrades, closedTrades) {
  if (!performance && !openTrades.length && !closedTrades.length) return null;

  if (performance) {
    return {
      ...performance,
      closedTrades,
    };
  }

  const returns = closedTrades.map((trade) => Number(trade?.pnl_percent || 0));
  const wins = returns.filter((value) => value > 0).length;
  const losses = returns.filter((value) => value < 0).length;
  const totalPnl = returns.reduce((sum, value) => sum + value, 0);
  const totalTrades = openTrades.length + closedTrades.length;

  return {
    ...(performance || {}),
    total_trades: totalTrades,
    open_trades: openTrades.length,
    closed_trades: closedTrades.length,
    wins,
    losses,
    long_trades: closedTrades.filter((trade) => trade?.side === "LONG").length,
    short_trades: closedTrades.filter((trade) => trade?.side === "SHORT").length,
    win_rate: closedTrades.length ? (wins / closedTrades.length) * 100 : 0,
    average_pnl_percent: closedTrades.length ? totalPnl / closedTrades.length : 0,
    total_pnl_percent: totalPnl,
    closedTrades,
  };
}

function normalizeTradeSide(value) {
  const side = String(value || "").toUpperCase();
  if (["BUY", "LONG", "STRONG_LONG"].includes(side)) return "LONG";
  if (["SELL", "SHORT", "STRONG_SHORT"].includes(side)) return "SHORT";
  return side || null;
}

function executorRowState(row, watchRow, candidates = []) {
  const side = normalizeTradeSide(
    watchRow?.combined_execution?.side || watchRow?.side || row?.type
  );
  const candidate = selectExecutorCandidate(candidates, row?.symbol, side);

  if (!candidate) return "no_queued_plan";
  return isCandidateExecutorReady(candidate) ? "executor_ready" : "executor_blocked";
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
  const [liveSocketConnected, setLiveSocketConnected] = useState(false);
  const [pageVisible, setPageVisible] = useState(
    () => document.visibilityState !== "hidden"
  );
  const [resumeTick, setResumeTick] = useState(0);
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    const handleVisibilityChange = () => {
      const visible = document.visibilityState !== "hidden";
      setPageVisible(visible);
      if (visible) {
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
        setLiveSocketConnected(true);
        setLiveStatus((current) => ({
          ...current,
          running: true,
          connected: true,
          state: "LIVE",
        }));
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
        setLiveSocketConnected(false);
        setLiveStatus((current) => ({ ...current, connected: false }));
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
    if (!pageVisible) return undefined;

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
    const id = liveSocketConnected
      ? null
      : window.setInterval(refreshSnapshot, LIVE_SNAPSHOT_FALLBACK_MS);

    return () => {
      cancelled = true;
      controller.abort();
      if (id) window.clearInterval(id);
    };
  }, [liveSocketConnected, pageVisible, symbols, resumeTick]);

  useEffect(() => {
    if (!pageVisible) return undefined;

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
  }, [pageVisible, symbols, resumeTick]);

  useEffect(() => {
    if (!pageVisible || liveSocketConnected) return undefined;

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

    const id = window.setInterval(pollLiveStatus, LIVE_STATUS_FALLBACK_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [liveSocketConnected, pageVisible, resumeTick]);

  useEffect(() => {
    if (!pageVisible) return undefined;

    let cancelled = false;
    const controller = new AbortController();
    let refreshTimer = null;

    async function load() {
      const isInitialLoad = !hasLoadedRef.current;
      if (isInitialLoad) {
        setLoading(true);
      }
      setError("");

      try {
        const requestErrors = [];
        const requests = [];

        if (pageNeedsSelectedBundle(activePage)) {
          requests.push(
            loadIntelligenceBundle({ view, signal: controller.signal })
              .then((selectedBundle) => {
                if (cancelled || !selectedBundle?.signal) return;
                setData((current) => mergeSelectedBundleData(current, view, selectedBundle));
                hasLoadedRef.current = true;
                setLoading(false);
              })
              .catch((exception) => {
                requestErrors.push(
                  `Selected intelligence: ${requestErrorMessage(exception, "request failed")}`
                );
              })
          );
        }

        requests.push(
          loadSignalBatch({ view, symbols, signal: controller.signal })
            .then((signalBatch) => {
              if (cancelled || !signalBatch) return;
              setData((current) => mergeSignalBatchData(current, signalBatch, symbols, view));
              hasLoadedRef.current = true;
              setLoading(false);
            })
            .catch((exception) => {
              requestErrors.push(
                `Signals: ${requestErrorMessage(exception, "request failed")}`
              );
            })
        );

        requests.push(
          loadDashboardBatches({ activePage, view, filters, auto, symbols, signal: controller.signal })
            .then((dashboardBatches) => {
              if (cancelled) return;
              setData((current) => mergeDashboardBatches(current, dashboardBatches, symbols, view));
              (dashboardBatches.errors || []).forEach((item) => {
                requestErrors.push(`${item.key}: ${item.message}`);
              });
            })
            .catch((exception) => {
              requestErrors.push(
                `Dashboard: ${requestErrorMessage(exception, "request failed")}`
              );
            })
        );

        await Promise.allSettled(requests);

        if (!cancelled && requestErrors.length) {
          setError(requestErrors.join(" · "));
        }
      } catch (exception) {
        if (!cancelled) {
          setError(exception instanceof Error ? exception.message : "Unable to load dashboard");
        }
      } finally {
        if (!cancelled) {
          hasLoadedRef.current = true;
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
    pageVisible,
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
  const watchlist = data.watchlist;
  const performance = data.performance || {};
  const accountRisk = data.accountRisk || null;
  const paperWallet = data.paperWallet || null;
  const ledgerScope = data.ledgerScope || null;
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

    const preferredSide = normalizeTradeSide(
      selectedRisk?.signal ||
      selectedDetail.signalType ||
      selectedSignal?.signal ||
      selectedSignal?.decision
    );

    return selectExecutorCandidate(
      selectedPaperTradeCandidates,
      view.symbol,
      preferredSide
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
      const combinedAllowed = watchRow?.combined_execution?.allowed === true;
      return { row, watchRow, risk, combinedAllowed };
    });
    const eligibleRows = rowStates.filter(({ combinedAllowed }) => combinedAllowed);
    const buyCount = rowStates.filter(({ row, watchRow }) => normalizeTradeSide(watchRow?.status === "READY" ? watchRow?.side : row.type) === "LONG").length;
    const sellCount = rowStates.filter(({ row, watchRow }) => normalizeTradeSide(watchRow?.status === "READY" ? watchRow?.side : row.type) === "SHORT").length;
    const waitCount = rows.length - buyCount - sellCount;
    const readyCount = eligibleRows.length;
    const persistedReadyCount = eligibleRows.filter(({ risk }) => String(risk.note || "").startsWith("Persisted risk:")).length;
    const computedReadyCount = eligibleRows.filter(({ risk }) => String(risk.note || "").startsWith("Computed risk:")).length;
    const fallbackReadyCount = eligibleRows.filter(({ risk }) => String(risk.note || "").startsWith("Trigger fallback:")).length;
    const executorReadyCount = rowStates.filter(({ row, watchRow }) => executorRowState(row, watchRow, selectedPaperTradeCandidates) === "executor_ready").length;
    const executorBlockedCount = rowStates.filter(({ row, watchRow }) => executorRowState(row, watchRow, selectedPaperTradeCandidates) === "executor_blocked").length;
    const noQueuedPlanCount = eligibleRows.filter(({ row, watchRow }) => executorRowState(row, watchRow, selectedPaperTradeCandidates) === "no_queued_plan").length;
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
      accountRisk,
      openTrades,
      tradePlan: activeTradePlan,
      multiTimeframe: data.selected.multiTimeframe,
    });
  }, [auto, view.symbol, selectedSignal, selectedRisk, performance, accountRisk, openTrades, activeTradePlan, data.selected.multiTimeframe]);
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

  const dailyPnl = performance.daily_pnl_percent ?? sumWithinDays(closedTrades, 1);
  const weeklyPnl = performance.weekly_pnl_percent ?? sumWithinDays(closedTrades, 7);
  const monthlyPnl = performance.monthly_pnl_percent ?? sumWithinDays(closedTrades, 30);
  const realizedPnl = performance.total_pnl_percent ?? sumPnl(closedTrades);
  const unrealizedPnl = sumPnl(openPositions, "unrealized_pnl_percent");
  const maxDrawdown = calculateMaxDrawdown(equitySeries);
  const winningTrades = performance.wins ?? closedTrades.filter((trade) => safeNumber(trade.pnl_percent, 0) > 0).length;
  const losingTrades = performance.losses ?? closedTrades.filter((trade) => safeNumber(trade.pnl_percent, 0) < 0).length;
  const closedTradeCount = performance.closed_trades ?? closedTrades.length;
  const winRate = performance.win_rate ?? (closedTradeCount ? (winningTrades / closedTradeCount) * 100 : 0);

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
    paperWallet,
    ledgerScope,
    candleSeries,
    volumeSeries,
    selectedRisk,
    selectedPaperTradeCandidate,
    paperTradeCandidates: selectedPaperTradeCandidates,
    equitySeries,
    pnlBySymbol,
    pnlBySide,
    tradeHistory,
    closedTradeCount,
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
    "market-move",
    "coin-details",
    "derivatives",
    "trading-details",
    "risk-controls",
    "auto-trading",
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
