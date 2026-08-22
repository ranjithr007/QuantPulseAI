import { formatTimeInIst, timestampMillis } from "../utils/formatters";

export function buildSignalRow(symbol, signal, watchlist) {
  const side = signalType(signal);
  const actionable = side !== "WAIT";
  const tradePlan = side === "WAIT" ? {} : signal?.trade_plan || {};
  const watchRow = (watchlist?.records || []).find((item) => item.symbol === symbol);
  const invalidation = signalInvalidationReason(signal);
  const directional = directionalSplit(signal, signalDirectionHint(signal));
  const probability = signal?.probability || {};

  return {
    symbol,
    timeframe: signal?.timeframe || null,
    type: side,
    confidence: rawSignalConfidence(signal),
    signalBias: signal?.bias || signal?.signal || "WAIT",
    signalScore: safeNumber(signal?.score, 0),
    probabilityLong: normalizedProbability(probability?.probabilities?.LONG ?? probability?.long_probability ?? signal?.long_probability),
    probabilityShort: normalizedProbability(probability?.probabilities?.SHORT ?? probability?.short_probability ?? signal?.short_probability),
    probabilityWait: normalizedProbability(probability?.probabilities?.WAIT ?? probability?.wait_probability ?? signal?.wait_probability),
    longPct: directional.longPct,
    shortPct: directional.shortPct,
    longSidePct: directional.longPct,
    shortSidePct: directional.shortPct,
    entry: actionable ? tradePlan.entry ?? null : null,
    stopLoss: actionable ? tradePlan.stop_loss ?? null : null,
    targets: actionable ? [tradePlan.target1, tradePlan.target2].filter((value) => value !== null && value !== undefined) : [],
    riskReward: actionable ? tradePlan.risk_reward ?? null : null,
    regime: signal?.bias || signal?.signal || "WAIT",
    reason: invalidation || formatReason(signal?.reasons, signal?.message),
    currentPrice: signal?.current_price ?? null,
    liveChangePct: safeNumber(signal?.live_market?.price_change_pct, null),
    liveUpdatedAt: signal?.live_market?.received_at || signal?.live_market?.event_time || null,
  };
}

export function buildSelectedDetail({
  symbol,
  timeframe,
  signal,
  diagnostics,
  candles,
  orderflow,
  smc,
  orderflowPayload,
  smcPayload,
  risk,
  aiScores,
  derivatives,
  multiTimeframe,
  predictionContext,
  prediction,
  timing,
  tradeSetup,
  entryTrigger,
}) {
  const currentPrice = safeNumber(signal?.current_price, candles?.[0]?.close_price || candles?.[0]?.close || 0);
  const signalBias = signalType(signal);
  const rawTradePlan = signal?.trade_plan || {};
  const directional = directionalSplit(signal, signalDirectionHint(signal));
  const tradePlan =
    signalBias === "WAIT"
      ? {
          entry: null,
          stop_loss: null,
          target1: null,
          target2: null,
          atr: rawTradePlan.atr ?? currentPrice * 0.01,
          risk_reward: 0,
        }
      : rawTradePlan;
  const regimeLabel = signal?.bias || diagnostics?.bias || "WAIT";
  const invalidation = signalInvalidationReason(signal);
  const regimeReason = invalidation || formatReason(diagnostics?.reasons, signal?.reasons?.[0]);
  const selectedOrderflow = firstRecord(orderflow);
  const selectedSmc = firstRecord(smc);
  const atr = safeNumber(tradePlan.atr, currentPrice * 0.01);
  const recentHigh = candles.length ? Math.max(...candles.map((item) => safeNumber(item.high_price ?? item.high, currentPrice))) : currentPrice;
  const recentLow = candles.length ? Math.min(...candles.map((item) => safeNumber(item.low_price ?? item.low, currentPrice))) : currentPrice;
  const resistanceLevels = {
    r1: currentPrice + atr,
    r2: Math.max(recentHigh + atr * 0.4, currentPrice + atr * 1.5),
    r3: Math.max(recentHigh + atr * 1.2, currentPrice + atr * 2.5),
  };
  const supportLevels = {
    s1: currentPrice - atr,
    s2: Math.min(recentLow - atr * 0.4, currentPrice - atr * 1.5),
    s3: Math.min(recentLow - atr * 1.2, currentPrice - atr * 2.5),
  };
  const freshness = diagnostics?.freshness?.candle || signal?.freshness || {};
  const whaleBuyCount = safeNumber(getValue(selectedOrderflow, "whale_buy_count", "whaleBuyCount", "BuyerStrength"), 0);
  const whaleSellCount = safeNumber(getValue(selectedOrderflow, "whale_sell_count", "whaleSellCount", "SellerStrength"), 0);
  const whaleBuyVolume = safeNumber(getValue(selectedOrderflow, "whale_buy_volume", "whaleBuyVolume", "BuyVolume", "buy_volume"), 0);
  const whaleSellVolume = safeNumber(getValue(selectedOrderflow, "whale_sell_volume", "whaleSellVolume", "SellVolume", "sell_volume"), 0);
  const whaleMaxVolume = Math.max(whaleBuyVolume, whaleSellVolume, 1);
  const orderflowTone = orderflowToneFromRecord(selectedOrderflow);
  const orderflowBadge = formatValue(
    getValue(selectedOrderflow, "aggressive_side", "aggressiveSide", "FlowSignal", "flow_signal")
  );
  const whaleTone = whaleBuyCount >= whaleSellCount ? "emerald" : "rose";
  const orderflowLines = selectedOrderflow
    ? [
        { label: "Aggressive side", value: orderflowBadge },
        { label: "Delta", value: formatNumber(getValue(selectedOrderflow, "delta", "Delta", "cumulative_delta", "CVD"), 2) },
        { label: "Absorption", value: formatValue(getValue(selectedOrderflow, "absorption_type", "Absorption")) },
        { label: "Exhaustion", value: formatValue(getValue(selectedOrderflow, "exhaustion_type", "Exhaustion")) },
      ]
    : [{ label: "Order flow", value: "No data" }];
  const smcTone = smcToneFromRecord(selectedSmc);
  const smcBadge = formatValue(getValue(selectedSmc, "smc_bias", "bias", "structure"));
  const smcLines = selectedSmc
    ? [
        { label: "Bias", value: formatValue(getValue(selectedSmc, "smc_bias", "bias")) },
        { label: "Structure", value: formatValue(getValue(selectedSmc, "structure")) },
        { label: "BOS", value: formatValue(getValue(selectedSmc, "bos_type")) },
        { label: "CHoCH", value: formatValue(getValue(selectedSmc, "choch_type")) },
        { label: "Order block", value: formatStructureLevel(getValue(selectedSmc, "order_block_type"), getValue(selectedSmc, "order_block_price")) },
        { label: "Liquidity sweep", value: formatSweepValue(selectedSmc) },
      ]
    : [{ label: "SMC", value: "No data" }];
  const breakdown = buildConfidenceBreakdown(signal, diagnostics, aiScores, selectedOrderflow, selectedSmc);
  const validationBreakdown = buildValidationBreakdown(signal, diagnostics, risk);
  const liquidityZones = {
    upper: currentPrice + atr * 1.75,
    lower: currentPrice - atr * 1.75,
  };
  const regimeTone = regimeToneFromLabel(regimeLabel);
  const predictionStack = predictionContext?.prediction_stack || multiTimeframe?.prediction_stack || multiTimeframe?.timeframes_used || [];
  const timingStack = timing?.timing_stack || entryTrigger?.timing_stack || entryTrigger?.entry_stack || multiTimeframe?.timing_stack || multiTimeframe?.entry_stack || [];

  return {
    symbol,
    timeframe,
    currentPrice,
    liveMarket: signal?.live_market || null,
    confidence: rawSignalConfidence(signal, diagnostics?.confidence),
    signalType: signalBias,
    signalBias: signal?.bias || "WAIT",
    invalidationReason: invalidation,
    freshness,
    regimeLabel,
    regimeTone,
    regimeReason,
    tradePlan,
    priceChangePct: priceChangePct(candles),
    resistanceLevels,
    supportLevels,
    longSidePct: directional.longPct,
    shortSidePct: directional.shortPct,
    orderflowTone,
    orderflowBadge,
    orderflowLines,
    smcTone,
    smcBadge,
    smcLines,
    whaleTone,
    whaleBuyCount,
    whaleSellCount,
    whaleBuyVolume,
    whaleSellVolume,
    whaleMaxVolume,
    liquidationZones: liquidityZones,
    breakdown,
    validationBreakdown,
    tradeSetup,
    entryTrigger,
    multiTimeframe,
    predictionContext,
    prediction,
    timing,
    predictionStack,
    timingStack,
    aiScores,
    derivatives,
    risk,
    selectedOrderflow,
    selectedSmc,
    selectedOrderflowPayload: orderflowPayload || null,
    selectedSmcPayload: smcPayload || null,
  };
}

function hasMeaningfulComponentScore(component) {
  if (!component || typeof component !== "object") {
    return false;
  }

  const score = Number(component.score);
  if (!Number.isFinite(score)) {
    return false;
  }

  if (score !== 0) {
    return true;
  }

  const reason = String(component.reason || "").trim().toLowerCase();
  if (!reason) {
    return false;
  }

  return !reason.startsWith("no ") && !reason.includes("no order flow score") && !reason.includes("no smc score");
}

export function evaluateAutoTrading({ auto, selectedSymbol, signal, risk, performance, accountRisk, openTrades, tradePlan, multiTimeframe }) {
  const tradeBlockers = [];
  const coinBlockers = [];
  const accountBlockers = [];
  const warnings = [];
  const signalSide = signalType(signal);
  const confidence = effectiveConfidence(signal);
  const stackState = timeframeStackState(multiTimeframe);
  const invalidation = signalInvalidationReason(signal);
  const dailyLoss = safeNumber(accountRisk?.daily_pnl_percent, 0);
  const directionAllowed =
    auto.direction === "BOTH" ||
    (auto.direction === "LONG" && signalSide === "BUY") ||
    (auto.direction === "SHORT" && signalSide === "SELL");

  if (!auto.enabled) accountBlockers.push("Automation paused");
  if (auto.locked) accountBlockers.push("Auto trading locked");
  if (auto.emergencyStop) accountBlockers.push("Emergency stop active");
  if (!auto.allowedSymbols.includes(selectedSymbol)) coinBlockers.push("Symbol not in allowlist");
  if (!directionAllowed) tradeBlockers.push("Direction not allowed");
  if (signalSide === "WAIT") tradeBlockers.push("Signal is WAIT");
  if (invalidation) tradeBlockers.push(invalidation);
  if (stackState === "MIXED_LIGHT" || stackState === "MIXED_STRONG") warnings.push("Timeframe stack is mixed");
  if (stackState === "MIXED_STRONG") tradeBlockers.push("Timeframe stack is strongly mixed");
  if (confidence < auto.minConfidence) tradeBlockers.push("Confidence below minimum");
  if (
    safeNumber(accountRisk?.open_trade_count, openTrades.length) >= auto.maxOpenTrades
    || safeNumber(performance?.open_trades, 0) >= auto.maxOpenTrades
  ) {
    accountBlockers.push("Account-wide open trade cap reached");
  }
  if (openTrades.some((trade) => String(trade?.symbol || "").toUpperCase() === String(selectedSymbol || "").toUpperCase())) {
    coinBlockers.push("Active trade already exists for this coin");
  }
  if (accountRisk?.limit_reached === true) accountBlockers.push("Account-wide daily loss limit reached");
  if (!accountRisk) warnings.push("Account daily P&L unavailable");
  if (risk?.is_usable === false) tradeBlockers.push("Risk decision not usable");
  if (tradePlan && safeNumber(tradePlan.risk_reward, 0) < 1) tradeBlockers.push("Risk reward is weak");

  const blockerScopes = { trade: tradeBlockers, coin: coinBlockers, account: accountBlockers };
  const reasons = [...accountBlockers, ...coinBlockers, ...tradeBlockers];
  const allowed = reasons.length === 0;
  const reason = allowed
    ? "Selected signal passes allowlist, direction, confidence, and risk checks."
    : `Automatic execution blocked by ${reasons.join(", ")}.`;

  return {
    allowed,
    reason,
    reasons,
    warnings,
    signalSide,
    confidence,
    rawConfidence: confidence,
    stackState,
    dailyLoss,
    accountRisk,
    blockerScopes,
    tradeBlockers,
    coinBlockers,
    accountBlockers,
  };
}

export function normalizeCandles(response) {
  const records = Array.isArray(response) ? response : response?.records || [];
  return [...records]
    .map((item, index) => {
      const rawTime = item.candle_time || item.time || item.created_at;
      const timestamp = dateValue(rawTime);

      return {
        time: formatShortTime(rawTime),
        chartTime: timestamp ? Math.floor(timestamp / 1000) : fallbackChartTime(index, records.length),
        sortTime: timestamp || index,
        open: safeNumber(item.open_price ?? item.open, 0),
        high: safeNumber(item.high_price ?? item.high, 0),
        low: safeNumber(item.low_price ?? item.low, 0),
        close: safeNumber(item.close_price ?? item.close, 0),
        volume: safeNumber(item.volume ?? item.Volume, 0),
      };
    })
    .sort((a, b) => a.sortTime - b.sortTime);
}

export function buildEquityCurve(trades) {
  let equity = 0;

  return trades
    .filter((trade) => trade.status === "CLOSED")
    .map((trade, index) => {
      equity += safeNumber(trade.pnl_percent, 0);
      return {
        index: index + 1,
        label: formatCompactIndex(index + 1),
        equity: Number(equity.toFixed(2)),
      };
    });
}

export function buildGroupPnL(trades, key) {
  const groups = new Map();

  trades
    .filter((trade) => trade.status === "CLOSED")
    .forEach((trade) => {
      const name = String(trade[key] || "UNKNOWN").toUpperCase();
      groups.set(name, (groups.get(name) || 0) + safeNumber(trade.pnl_percent, 0));
    });

  return [...groups.entries()]
    .map(([name, value]) => ({ name, value: Number(value.toFixed(2)) }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}

export function calculateMaxDrawdown(series) {
  let peak = -Infinity;
  let drawdown = 0;

  series.forEach((point) => {
    peak = Math.max(peak, point.equity);
    const trough = peak - point.equity;
    drawdown = Math.max(drawdown, trough);
  });

  return Number(drawdown.toFixed(2));
}

export function sumPnl(trades, field = "pnl_percent") {
  return Number(trades.reduce((sum, trade) => sum + safeNumber(trade[field], 0), 0).toFixed(2));
}

export function sumWithinDays(trades, days, field = "pnl_percent") {
  const now = Date.now();
  return Number(
    trades
      .filter((trade) => {
        const when = trade.closed_at || trade.created_at || trade.opened_at;
        if (!when) return false;
        const diff = now - timestampMillis(when);
        return diff >= 0 && diff <= days * 24 * 60 * 60 * 1000;
      })
      .reduce((sum, trade) => sum + safeNumber(trade[field], 0), 0)
      .toFixed(2)
  );
}

export function estimatePnlPercent(side, entry, current) {
  const start = safeNumber(entry, 0);
  const now = safeNumber(current, start);
  if (!start) return 0;
  if (String(side).toUpperCase() === "SHORT") {
    return Number((((start - now) / start) * 100).toFixed(2));
  }
  return Number((((now - start) / start) * 100).toFixed(2));
}

export function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function dateValue(value) {
  return timestampMillis(value);
}

function buildConfidenceBreakdown(signal, diagnostics, aiScores, selectedOrderflow, selectedSmc) {
  const componentScores = diagnostics?.component_scores || {};
  const signalConfidence = rawSignalConfidence(signal, diagnostics?.confidence);
  const aiScore = safeNumber(
    aiScores?.computed?.final_score ?? aiScores?.latest?.final_score ?? aiScores?.final_score,
    signalConfidence
  );
  const orderflowComponent = hasMeaningfulComponentScore(componentScores.orderflow)
    ? componentScores.orderflow
    : fallbackOrderflowComponent(selectedOrderflow) || componentScores.orderflow || null;
  const smcComponent = hasMeaningfulComponentScore(componentScores.smc)
    ? componentScores.smc
    : fallbackSmcComponent(selectedSmc) || componentScores.smc || null;

  return [
    {
      label: "Signal confidence",
      score: signalConfidence,
      reason: signal?.signal || "WAIT",
      width: clamp(signalConfidence, 0, 100),
    },
    {
      label: "Feature",
      score: safeNumber(componentScores.feature?.score, 0),
      reason: componentScores.feature?.reason || "No feature score",
      width: clamp(Math.abs(safeNumber(componentScores.feature?.score, 0)) * 2, 0, 100),
    },
    {
      label: "Regime",
      score: safeNumber(componentScores.regime?.score, 0),
      reason: componentScores.regime?.reason || "No regime score",
      width: clamp(Math.abs(safeNumber(componentScores.regime?.score, 0)) * 2, 0, 100),
    },
    {
      label: "Order flow",
      score: safeNumber(orderflowComponent?.score, 0),
      reason: orderflowComponent?.reason || "No order flow score",
      width: clamp(Math.abs(safeNumber(orderflowComponent?.score, 0)) * 2, 0, 100),
    },
    {
      label: "SMC",
      score: safeNumber(smcComponent?.score, 0),
      reason: smcComponent?.reason || "No SMC score",
      width: clamp(Math.abs(safeNumber(smcComponent?.score, 0)) * 2, 0, 100),
    },
    {
      label: "AI score",
      score: aiScore,
      reason: aiScores?.computed?.bias || aiScores?.latest?.bias || aiScores?.bias || "Computed",
      width: clamp(aiScore, 0, 100),
    },
  ];
}

function buildValidationBreakdown(signal, diagnostics, risk) {
  const freshnessScore = diagnostics?.freshness?.candle?.is_stale ? 15 : 85;
  const contradictionScore = diagnostics?.contradiction?.conflict_score
    ? Math.max(0, 100 - safeNumber(diagnostics.contradiction.conflict_score, 0))
    : 60;
  const probabilityDecision = String(
    signal?.probability?.decision || signal?.probability_decision || "WAIT"
  ).toUpperCase();
  const probabilityConfidence = safeNumber(
    signal?.probability?.confidence,
    signal?.[`${probabilityDecision.toLowerCase()}_probability`] ?? 0
  );

  return [
    {
      label: "Decision probability",
      score: probabilityConfidence,
      reason: `${probabilityDecision} probability`,
      width: clamp(probabilityConfidence, 0, 100),
    },
    {
      label: "Freshness",
      score: freshnessScore,
      reason: risk?.status || "Freshness check",
      width: clamp(freshnessScore, 0, 100),
    },
    {
      label: "Contradiction",
      score: contradictionScore,
      reason: diagnostics?.contradiction?.summary || "No contradiction summary",
      width: clamp(contradictionScore, 0, 100),
    },
  ];
}

function fallbackOrderflowComponent(record) {
  const resolved = firstRecord(record);
  if (!resolved) {
    return null;
  }

  const signal = String(
    getValue(resolved, "FlowSignal", "flow_signal", "aggressive_side", "aggressiveSide") || ""
  ).toUpperCase();
  const delta = safeNumber(getValue(resolved, "delta", "Delta", "cumulative_delta", "CVD"), 0);

  if (signal === "BUYERS_CONTROL") {
    return { score: 25, reason: "Buyers control flow" };
  }
  if (signal === "SELLERS_CONTROL") {
    return { score: -25, reason: "Sellers control flow" };
  }
  if (signal === "POSSIBLE_BUY_REVERSAL") {
    return { score: 15, reason: "Buyer absorption hints at reversal" };
  }
  if (signal === "POSSIBLE_SELL_REVERSAL") {
    return { score: -15, reason: "Seller absorption hints at reversal" };
  }
  if (delta > 0) {
    return { score: 10, reason: "Positive orderflow delta" };
  }
  if (delta < 0) {
    return { score: -10, reason: "Negative orderflow delta" };
  }

  return null;
}

function fallbackSmcComponent(record) {
  const resolved = firstRecord(record);
  if (!resolved) {
    return null;
  }

  const bias = String(getValue(resolved, "smc_bias", "bias") || "").toUpperCase();
  const structure = String(getValue(resolved, "structure", "bos_type", "choch_type") || "").toUpperCase();

  if (bias === "LONG") {
    return { score: 30, reason: "SMC bullish" };
  }
  if (bias === "SHORT") {
    return { score: -30, reason: "SMC bearish" };
  }
  if (structure.includes("BULL") || structure.includes("LONG")) {
    return { score: 20, reason: "Bullish SMC structure" };
  }
  if (structure.includes("BEAR") || structure.includes("SHORT")) {
    return { score: -20, reason: "Bearish SMC structure" };
  }

  return null;
}

function priceChangePct(candles) {
  if (candles.length < 2) return 0;
  const latest = candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  const latestClose = safeNumber(latest.close_price ?? latest.close, 0);
  const prevClose = safeNumber(prev.close_price ?? prev.close, 0);
  if (!prevClose) return 0;
  return Number((((latestClose - prevClose) / prevClose) * 100).toFixed(2));
}

function signalType(signal) {
  if (signalInvalidationReason(signal)) return "WAIT";

  const rawSignal = String(signal?.signal || "").toUpperCase();
  if (rawSignal === "LONG" || rawSignal === "BUY") return "BUY";
  if (rawSignal === "SHORT" || rawSignal === "SELL") return "SELL";
  if (rawSignal === "WAIT" || rawSignal === "NO_DATA") return "WAIT";

  const bias = String(signal?.bias || "").toUpperCase();
  if (bias.includes("LONG") && rawSignal !== "WAIT") return "BUY";
  if (bias.includes("SHORT") && rawSignal !== "WAIT") return "SELL";
  return "WAIT";
}

function timeframeStackState(multiTimeframe) {
  const confirmation = multiTimeframe?.confirmation || multiTimeframe || {};
  return String(confirmation.stack_state || "").toUpperCase();
}

function directionalSplit(signal, fallbackSide = "WAIT") {
  const { longProbability, shortProbability } = extractProbabilityPair(signal);

  if ((longProbability !== null || shortProbability !== null) && (longProbability > 0 || shortProbability > 0)) {
    const longBase = longProbability ?? 0;
    const shortBase = shortProbability ?? 0;
    const total = longBase + shortBase;

    if (total > 0) {
      return {
        longPct: Number(((longBase / total) * 100).toFixed(2)),
        shortPct: Number(((shortBase / total) * 100).toFixed(2)),
      };
    }
  }

  const confidence = rawSignalConfidence(signal);
  const direction = fallbackSide === "BUY" || fallbackSide === "SELL" ? fallbackSide : "WAIT";

  if (direction === "BUY") {
    const strength = Math.max(0, Math.min(100, confidence));
    const longPct = Number((50 + strength / 2).toFixed(2));
    return {
      longPct,
      shortPct: Number((100 - longPct).toFixed(2)),
    };
  }

  if (direction === "SELL") {
    const strength = Math.max(0, Math.min(100, confidence));
    const longPct = Number((50 - strength / 2).toFixed(2));
    return {
      longPct,
      shortPct: Number((100 - longPct).toFixed(2)),
    };
  }

  return {
    longPct: 50,
    shortPct: 50,
  };
}

function signalDirectionHint(signal) {
  const rawSignal = String(signal?.signal || "").toUpperCase();
  if (rawSignal === "LONG" || rawSignal === "BUY") return "BUY";
  if (rawSignal === "SHORT" || rawSignal === "SELL") return "SELL";

  const bias = String(signal?.bias || "").toUpperCase();
  if (bias.includes("LONG")) return "BUY";
  if (bias.includes("SHORT")) return "SELL";

  const score = safeNumber(signal?.score, 0);
  if (score > 0) return "BUY";
  if (score < 0) return "SELL";

  const probabilityDecision = String(signal?.probability?.decision || "").toUpperCase();
  if (probabilityDecision === "LONG") return "BUY";
  if (probabilityDecision === "SHORT") return "SELL";

  return "WAIT";
}

function displayDirection(signal, fallbackSide = "WAIT") {
  if (fallbackSide === "BUY" || fallbackSide === "SELL") {
    return fallbackSide;
  }

  const invalidation = signalInvalidationReason(signal);
  const hardInvalidation =
    invalidation &&
    !String(invalidation).startsWith("Probability engine decision:");

  if (hardInvalidation) {
    return "WAIT";
  }

  const bias = String(signal?.bias || "").toUpperCase();
  if (bias.includes("LONG")) return "BUY";
  if (bias.includes("SHORT")) return "SELL";

  const score = safeNumber(signal?.score, 0);
  if (score > 0) return "BUY";
  if (score < 0) return "SELL";

  const probabilityDecision = String(signal?.probability?.decision || "").toUpperCase();
  if (probabilityDecision === "LONG") return "BUY";
  if (probabilityDecision === "SHORT") return "SELL";

  return "WAIT";
}

function extractProbabilityPair(signal) {
  const probability = signal?.probability || {};
  const candidates = [
    [signal?.probabilityLong, signal?.probabilityShort],
    [signal?.probability_long, signal?.probability_short],
    [signal?.longProbability, signal?.shortProbability],
    [signal?.long_probability, signal?.short_probability],
    [probability.probabilities?.LONG, probability.probabilities?.SHORT],
    [probability.probabilities?.long, probability.probabilities?.short],
    [probability.probabilities?.long_probability, probability.probabilities?.short_probability],
    [probability.LONG, probability.SHORT],
    [probability.long, probability.short],
    [probability.long_probability, probability.short_probability],
    [signal?.long_probability, signal?.short_probability],
    [signal?.probabilities?.LONG, signal?.probabilities?.SHORT],
    [signal?.probabilities?.long, signal?.probabilities?.short],
    [signal?.probabilities?.long_probability, signal?.probabilities?.short_probability],
  ];

  for (const [longValue, shortValue] of candidates) {
    const longProbability = normalizedProbability(longValue);
    const shortProbability = normalizedProbability(shortValue);
    if (longProbability !== null || shortProbability !== null) {
      return {
        longProbability,
        shortProbability,
      };
    }
  }

  return {
    longProbability: null,
    shortProbability: null,
  };
}

function signalInvalidationReason(signal) {
  if (!signal) return "";

  const contradictionStatus = String(signal?.contradiction?.status || "").toUpperCase();
  const contradictionTradeAllowed = signal?.contradiction?.trade_allowed;
  const probabilityDecision = String(signal?.probability?.decision || "").toUpperCase();
  const probabilityActionable = signal?.probability?.actionable;
  const freshness = signal?.freshness;
  const rawSignal = String(signal?.signal || "").toUpperCase();

  if (freshness?.is_stale) return "Signal data is stale";
  if (contradictionStatus === "INVALIDATED") return signal?.contradiction?.summary || "Signal invalidated by contradiction engine";
  if (contradictionTradeAllowed === false) return signal?.contradiction?.summary || "Trade blocked by contradiction engine";
  if (probabilityActionable === false && rawSignal === "WAIT") return `Probability engine decision: ${probabilityDecision || "WAIT"}`;
  if (probabilityDecision === "WAIT" && rawSignal === "WAIT") return "Probability engine decision: WAIT";

  return "";
}

function effectiveConfidence(signal, fallback = 0) {
  if (!signal) return safeNumber(fallback, 0);
  if (String(signal?.status || "").toUpperCase() === "FAILED") {
    return safeNumber(fallback, 0);
  }
  if (signalInvalidationReason(signal)) {
    return safeNumber(signal?.probability?.confidence, fallback);
  }
  return safeNumber(signal?.confidence, fallback);
}

function rawSignalConfidence(signal, fallback = 0) {
  if (!signal || String(signal?.status || "").toUpperCase() === "FAILED") {
    return safeNumber(fallback, 0);
  }
  return safeNumber(signal?.confidence, fallback);
}

function normalizedProbability(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return null;
  return number <= 1 ? number * 100 : number;
}

function formatReason(reasons, fallback) {
  if (Array.isArray(reasons) && reasons.length) {
    return reasons.slice(0, 2).join(" - ");
  }
  if (typeof reasons === "string" && reasons) return reasons;
  return fallback || "No active reason";
}

function orderflowToneFromRecord(record) {
  if (!record) return "slate";
  const delta = safeNumber(getValue(record, "delta", "Delta", "cumulative_delta", "CVD"), 0);
  if (delta > 0) return "emerald";
  if (delta < 0) return "rose";
  return "amber";
}

function smcToneFromRecord(record) {
  if (!record) return "slate";

  const bias = String(getValue(record, "smc_bias", "bias") || "").toUpperCase();
  const structure = String(getValue(record, "structure", "bos_type", "choch_type") || "").toUpperCase();

  if (bias === "LONG" || structure.includes("BULL")) return "emerald";
  if (bias === "SHORT" || structure.includes("BEAR")) return "rose";
  if (bias === "NEUTRAL") return "amber";
  return "cyan";
}

function regimeToneFromLabel(label) {
  const text = String(label || "").toUpperCase();
  if (text.includes("BULL")) return "emerald";
  if (text.includes("BEAR")) return "rose";
  if (text.includes("MIXED")) return "amber";
  if (text.includes("NEUTRAL")) return "slate";
  return "cyan";
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  return String(value);
}

function firstRecord(value) {
  if (Array.isArray(value)) {
    return value.find((item) => item && typeof item === "object") || null;
  }

  if (value && typeof value === "object") {
    return value;
  }

  return null;
}

function formatStructureLevel(type, price) {
  const label = formatValue(type);
  if (price === null || price === undefined || price === "") {
    return label;
  }

  return `${label} @ ${formatNumber(price, 6)}`;
}

function formatSweepValue(record) {
  const resolved = firstRecord(record);
  const detected = getValue(resolved, "liquidity_sweep");
  const price = getValue(resolved, "sweep_price");

  if (detected === false) {
    return "NONE";
  }

  if (price === null || price === undefined || price === "") {
    return detected ? "DETECTED" : "N/A";
  }

  return formatNumber(price, 6);
}

function getValue(item, ...keys) {
  if (!item) return null;

  const normalizedEntries = Object.entries(item).map(([entryKey, entryValue]) => [normalizeLookupKey(entryKey), entryValue]);

  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(item, key) && item[key] !== null && item[key] !== undefined) {
      return item[key];
    }

    const normalizedKey = normalizeLookupKey(key);
    const normalizedMatch = normalizedEntries.find(([entryKey]) => entryKey === normalizedKey);
    if (normalizedMatch && normalizedMatch[1] !== null && normalizedMatch[1] !== undefined) {
      return normalizedMatch[1];
    }
  }
  return null;
}

function normalizeLookupKey(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatShortTime(value) {
  if (!value) return "N/A";
  return formatTimeInIst(value, String(value));
}

function formatCompactIndex(index) {
  return `#${index}`;
}

function fallbackChartTime(index, total) {
  const secondsPerCandle = 300;
  return Math.floor(Date.now() / 1000) - Math.max(total - index, 0) * secondsPerCandle;
}
