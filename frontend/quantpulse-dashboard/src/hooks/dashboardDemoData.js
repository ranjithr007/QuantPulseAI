export function buildDemoDashboardData(view, symbols) {
  const priceMap = {
    BTCUSDT: 66515.99,
    ETHUSDT: 1773.3,
    XRPUSDT: 1.2362,
    SOLUSDT: 74.54,
    BNBUSDT: 613.39,
    DOGEUSDT: 0.1335,
  };

  const signalSpecs = {
    BTCUSDT: { signal: "LONG", bias: "BULLISH_PULLBACK", confidence: 78, score: 62, regime: "TRENDING_BULL", rr: 2.4 },
    ETHUSDT: { signal: "LONG", bias: "BULLISH_PULLBACK", confidence: 74, score: 58, regime: "TRENDING_BULL", rr: 2.2 },
    XRPUSDT: { signal: "WAIT", bias: "MIXED", confidence: 35, score: 4, regime: "RANGE", rr: 0 },
    SOLUSDT: { signal: "WAIT", bias: "NEUTRAL", confidence: 24, score: 5, regime: "RANGE", rr: 0 },
    BNBUSDT: { signal: "SHORT", bias: "BEARISH_CONTINUATION", confidence: 69, score: -48, regime: "TRENDING_BEAR", rr: 1.9 },
    DOGEUSDT: { signal: "LONG", bias: "BULLISH_PULLBACK", confidence: 57, score: 23, regime: "MIXED", rr: 1.7 },
  };

  const signalsBySymbol = Object.fromEntries(
    symbols.map((symbol) => [symbol, buildDemoSignal(symbol, priceMap[symbol], signalSpecs[symbol])])
  );
  const selectedSignal = signalsBySymbol[view.symbol] || buildDemoSignal(view.symbol, priceMap[view.symbol] || 1, signalSpecs[view.symbol] || signalSpecs.BTCUSDT);
  const candles = buildDemoCandles(selectedSignal.current_price || priceMap[view.symbol] || 1, view.timeframe);
  const diagnostics = buildDemoDiagnostics(view.symbol, selectedSignal, view.timeframe, candles);
  const orderflow = buildDemoOrderflow(view.symbol, selectedSignal);
  const smc = buildDemoSmc(view.symbol, selectedSignal);
  const risk = buildDemoRisk(view.symbol, selectedSignal);
  const aiScores = buildDemoAiScores(selectedSignal);
  const multiTimeframe = buildDemoMultiTimeframe(selectedSignal);
  const tradeSetup = buildDemoTradeSetup(selectedSignal);
  const entryTrigger = buildDemoEntryTrigger(selectedSignal);

  const watchlistRecords = symbols.map((symbol) => {
    const signal = signalsBySymbol[symbol];
    const tradePlan = signal.trade_plan || {};
    const type = signalType(signal);
    const side = type === "WAIT" ? null : type === "BUY" ? "LONG" : "SHORT";
    return {
      symbol,
      status: signal.signal === "WAIT" ? "WAIT" : "READY",
      side,
      overall_bias: signal.bias,
      trade_permission: side === "LONG" ? "LONG_ONLY" : side === "SHORT" ? "SHORT_ALLOWED" : "WAIT",
      reason: signal.reasons?.[0] || "Demo signal",
      failed_conditions: signal.signal === "WAIT" ? ["five_minute_bias"] : [],
      bias_5m: signal.bias,
      bias_15m: signal.bias === "MIXED" ? "NEUTRAL" : signal.bias === "BEARISH_CONTINUATION" ? "SHORT" : "LONG",
      bias_1h: signal.bias === "BEARISH_CONTINUATION" ? "SHORT" : "LONG",
      score_5m: signal.score,
      entry: tradePlan.entry,
      stop_loss: tradePlan.stop_loss,
      target1: tradePlan.target1,
      risk_reward: tradePlan.risk_reward,
      price_precision: signal.symbol === "XRPUSDT" ? 4 : 2,
    };
  });

  const watchlistSummary = watchlistRecords.reduce(
    (acc, item) => {
      if (item.status === "READY") acc.ready += 1;
      if (item.status === "WAIT") acc.wait += 1;
      if (item.side === "LONG") acc.long += 1;
      if (item.side === "SHORT") acc.short += 1;
      if (!item.side) acc.no_side += 1;
      return acc;
    },
    { ready: 0, wait: 0, long: 0, short: 0, no_side: 0 }
  );

  const openTrades = buildDemoOpenTrades(selectedSignal, priceMap);
  const closedTrades = buildDemoClosedTrades();
  const performance = buildDemoPerformance(openTrades, closedTrades);

  return {
    signalsBySymbol,
    watchlist: {
      source: "signal_watchlist",
      mode: view.mode,
      timeframes: view.timeframe,
      filters: { status: null, side: null, failed_max: null },
      sort: "priority",
      count: watchlistRecords.length,
      total_count: watchlistRecords.length,
      summary: watchlistSummary,
      records: watchlistRecords,
    },
    pipeline: { source: "pipeline_status", status: "DEMO_READY", mode: view.mode },
    performance,
    openTrades,
    closedTrades,
    selected: {
      signal: selectedSignal,
      diagnostics,
      candles: { source: "demo_market_candles", symbol: view.symbol, timeframe: view.timeframe, count: candles.length, records: candles },
      orderflow: { source: "demo_orderflow", symbol: view.symbol, timeframe: view.timeframe, count: orderflow.length, records: orderflow },
      smc: { source: "demo_smc", symbol: view.symbol, timeframe: view.timeframe, count: smc.length, records: smc },
      risk,
      aiScores,
      multiTimeframe,
      predictionContext: multiTimeframe,
      prediction: tradeSetup,
      timing: entryTrigger,
      tradeSetup,
      entryTrigger,
    },
    lastRefresh: new Date(),
  };
}

function buildDemoSignal(symbol, currentPrice, spec = {}) {
  const tradePlan = spec.signal === "WAIT"
    ? { entry: null, stop_loss: null, target1: null, target2: null, atr: currentPrice * 0.008, risk_reward: 0 }
    : spec.signal === "SHORT"
      ? {
          entry: roundPrice(currentPrice * 0.998),
          stop_loss: roundPrice(currentPrice * 1.008),
          target1: roundPrice(currentPrice * 0.985),
          target2: roundPrice(currentPrice * 0.97),
          atr: currentPrice * 0.008,
          risk_reward: spec.rr,
        }
      : {
          entry: roundPrice(currentPrice * 1.001),
          stop_loss: roundPrice(currentPrice * 0.992),
          target1: roundPrice(currentPrice * 1.02),
          target2: roundPrice(currentPrice * 1.04),
          atr: currentPrice * 0.008,
          risk_reward: spec.rr,
        };

  return {
    symbol,
    timeframe: "1h",
    source: "demo_current",
    signal: spec.signal || "WAIT",
    bias: spec.bias || "NEUTRAL",
    confidence: spec.confidence || 0,
    score: spec.score || 0,
    current_price: currentPrice,
    candle_time: new Date().toISOString(),
    freshness: {
      data_timestamp: new Date().toISOString(),
      data_age_seconds: 0,
      is_future: false,
      future_by_seconds: 0,
      is_stale: false,
      stale_after_seconds: 900,
    },
    trade_plan: tradePlan,
    reasons:
      spec.signal === "SHORT"
        ? ["Bearish trend", "Sellers control flow", "Positive risk reward"]
        : spec.signal === "WAIT"
          ? ["Feature trend neutral", "Waiting for confirmation"]
          : ["Feature trend bullish", "Bull regime", "Buyers control flow"],
  };
}

function buildDemoCandles(currentPrice, timeframe) {
  const now = Date.now();
  return Array.from({ length: 32 }, (_, index) => {
    const t = index / 3;
    const base = currentPrice * (1 + Math.sin(t) * 0.004 + (index - 16) * 0.0007);
    const open = base * (1 + Math.sin(t + 0.3) * 0.001);
    const close = base * (1 + Math.cos(t + 0.6) * 0.001);
    return {
      time: new Date(now - (31 - index) * 5 * 60 * 1000).toISOString(),
      candle_time: new Date(now - (31 - index) * 5 * 60 * 1000).toISOString(),
      open_price: roundPrice(open),
      high_price: roundPrice(Math.max(open, close) * 1.003),
      low_price: roundPrice(Math.min(open, close) * 0.997),
      close_price: roundPrice(close),
      volume: Math.round(1000 + index * 120 + Math.abs(Math.sin(t)) * 500),
      timeframe,
    };
  });
}

function buildDemoDiagnostics(symbol, signal, timeframe, candles) {
  const bullish = signal.signal !== "SHORT";
  return {
    symbol,
    timeframe,
    source: "demo_diagnostics",
    signal: signal.signal,
    bias: signal.bias,
    confidence: signal.confidence,
    score: signal.score,
    current_price: signal.current_price,
    candle_time: signal.candle_time,
    freshness: signal.freshness,
    component_scores: {
      feature: { score: bullish ? 22 : -18, reason: bullish ? "Bullish momentum" : "Bearish momentum", value: bullish ? "BULLISH" : "BEARISH" },
      regime: { score: bullish ? 18 : -16, reason: bullish ? "Aligned regime" : "Bear regime", value: bullish ? "LONG" : "SHORT" },
      orderflow: { score: bullish ? 14 : -12, reason: bullish ? "Buyers control flow" : "Sellers control flow", value: bullish ? "BUYERS_CONTROL" : "SELLERS_CONTROL" },
      smc: { score: bullish ? 10 : -8, reason: bullish ? "Bullish structure" : "Bearish structure", value: bullish ? "BULL" : "BEAR" },
    },
    reasons: signal.reasons,
    contradiction: { summary: "Demo mode - no live contradiction analysis", conflict_score: 0 },
    probability: {
      source: "demo_probability",
      symbol,
      timeframe,
      signal: signal.signal,
      bias: signal.bias,
      decision: signal.signal === "WAIT" ? "WAIT" : "TRADE",
      actionable: signal.signal !== "WAIT",
      status: "DEMO",
      confidence: signal.confidence,
      probabilities: {
        LONG: bullish ? 0.74 : 0.18,
        SHORT: bullish ? 0.16 : 0.72,
        WAIT: signal.signal === "WAIT" ? 0.63 : 0.14,
      },
    },
    inputs: {
      feature: { data_timestamp: candles[0]?.candle_time, data_age_seconds: 0, is_future: false, future_by_seconds: 0, is_stale: false, stale_after_seconds: 900 },
      regime: { data_timestamp: candles[0]?.candle_time, data_age_seconds: 0, is_future: false, future_by_seconds: 0, is_stale: false, stale_after_seconds: 900 },
      orderflow: { data_timestamp: candles[0]?.candle_time, data_age_seconds: 0, is_future: false, future_by_seconds: 0, is_stale: false, stale_after_seconds: 900 },
      smc: { data_timestamp: candles[0]?.candle_time, data_age_seconds: 0, is_future: false, future_by_seconds: 0, is_stale: false, stale_after_seconds: 900 },
    },
  };
}

function buildDemoOrderflow(symbol, signal) {
  const bullish = signal.signal !== "SHORT";
  return [
    {
      symbol,
      timeframe: "1h",
      aggressive_side: bullish ? "BUY" : "SELL",
      delta: bullish ? 185.4 : -142.2,
      absorption_type: bullish ? "BUYER_ABSORPTION" : "SELLER_ABSORPTION",
      exhaustion_type: bullish ? "SELLER_EXHAUSTION" : "BUYER_EXHAUSTION",
      whale_buy_count: bullish ? 8 : 2,
      whale_sell_count: bullish ? 3 : 7,
      whale_buy_volume: bullish ? 1200 : 420,
      whale_sell_volume: bullish ? 430 : 1150,
      created_at: new Date().toISOString(),
    },
  ];
}

function buildDemoSmc(symbol, signal) {
  const bullish = signal.signal !== "SHORT";
  return [
    {
      symbol,
      timeframe: "1h",
      bos_detected: bullish,
      bos_type: bullish ? "BULL" : "BEAR",
      choch_detected: !bullish,
      choch_type: !bullish ? "BEAR" : "NONE",
      structure: bullish ? "UPTREND" : "DOWNTREND",
      order_block_type: bullish ? "BULLISH" : "BEARISH",
      order_block_price: signal.current_price * (bullish ? 0.992 : 1.008),
      fvg_detected: true,
      fvg_price: signal.current_price * (bullish ? 1.004 : 0.996),
      liquidity_sweep: false,
      sweep_price: null,
      smc_bias: bullish ? "LONG" : "SHORT",
      confidence: bullish ? 72 : 67,
      created_at: new Date().toISOString(),
    },
  ];
}

function buildDemoRisk(symbol, signal) {
  return {
    symbol,
    source: "risk_decisions",
    status: "DEMO",
    signal: signal.signal,
    decision: signal.signal === "WAIT" ? "REJECT" : "APPROVE",
    entry_price: signal.trade_plan.entry,
    stop_loss: signal.trade_plan.stop_loss,
    target1: signal.trade_plan.target1,
    target2: signal.trade_plan.target2,
    risk_reward: signal.trade_plan.risk_reward,
    position_size: signal.signal === "WAIT" ? null : 1.25,
    risk_percent: 1.0,
    confidence: signal.confidence,
    created_at: new Date().toISOString(),
    freshness: {
      data_timestamp: new Date().toISOString(),
      data_age_seconds: 0,
      is_future: false,
      future_by_seconds: 0,
      is_stale: false,
      stale_after_seconds: 900,
    },
    is_valid_trade_plan: signal.signal !== "WAIT",
    is_usable: signal.signal !== "WAIT",
    ignored_reasons: signal.signal === "WAIT" ? ["Signal is WAIT"] : [],
    validation_errors: [],
  };
}

function buildDemoAiScores(signal) {
  return {
    symbol: signal.symbol,
    count: 1,
    latest: {
      source: "ai_scores",
      symbol: signal.symbol,
      timeframe: "1h",
      final_score: signal.score,
      bias: signal.bias,
      created_at: new Date().toISOString(),
    },
    computed: {
      source: "ai_scores",
      symbol: signal.symbol,
      timeframe: "1h",
      final_score: signal.score,
      bias: signal.bias,
      created_at: new Date().toISOString(),
    },
    records: [],
  };
}

function buildDemoMultiTimeframe(signal) {
  const stackState = signal.bias === "BULLISH_PULLBACK" || signal.bias === "BEARISH_CONTINUATION" || signal.bias === "BULLISH_CONTINUATION" || signal.bias === "BEARISH_PULLBACK" || signal.bias === "BULLISH_ALIGNMENT" || signal.bias === "BEARISH_ALIGNMENT"
    ? "ALIGNED"
    : signal.bias === "MIXED"
      ? "MIXED_STRONG"
      : "MIXED_LIGHT";
  return {
    symbol: signal.symbol,
    source: "multi_timeframe_confirmation",
    overall_bias: signal.bias,
    trade_permission: signal.signal === "SHORT" ? "SHORT_ALLOWED" : signal.signal === "WAIT" ? "WAIT" : "LONG_ONLY",
    timeframes_used: ["1h", "2h", "4h", "1d"],
    prediction_stack: ["1h", "2h", "4h", "1d"],
    entry_stack: [],
    timing_stack: [],
    confirmation: {
      overall_bias: signal.bias,
      trade_permission: signal.signal === "SHORT" ? "SHORT_ALLOWED" : signal.signal === "WAIT" ? "WAIT" : "LONG_ONLY",
      stack_state: stackState,
      confidence_penalty: stackState === "MIXED_STRONG" ? 15 : stackState === "MIXED_LIGHT" ? 5 : 0,
    },
  };
}

function buildDemoTradeSetup(signal) {
  return {
    symbol: signal.symbol,
    source: "multi_timeframe_trade_setup",
    mode: "intraday",
    setup: {
      status: signal.signal === "WAIT" ? "WAIT" : "READY",
      side: signal.signal === "SHORT" ? "SHORT" : signal.signal === "WAIT" ? null : "LONG",
      reason: signal.signal === "WAIT" ? "Waiting for stabilization" : signal.signal === "SHORT" ? "Short pullback confirmed" : "Long pullback confirmed",
    },
    confirmation: buildDemoMultiTimeframe(signal).confirmation,
    scenario: { source: "demo_scenario" },
    trade_plan: signal.trade_plan,
    trade_plan_validation: { is_valid: signal.signal !== "WAIT", errors: [] },
    timeframes: [],
    prediction_stack: ["1h", "2h", "4h", "1d"],
    entry_stack: [],
    timing_stack: [],
  };
}

function buildDemoEntryTrigger(signal) {
  const side = signal.signal === "SHORT" ? "SHORT" : signal.signal === "WAIT" ? null : "LONG";
  return {
    symbol: signal.symbol,
    source: "multi_timeframe_entry_trigger",
    trigger: {
      status: signal.signal === "WAIT" ? "WAIT" : "READY",
      side,
      reason: signal.signal === "WAIT" ? "Waiting for higher-timeframe alignment" : `${side} entry trigger is ready`,
      conditions: [
        { name: "entry_timeframe_bias", passed: signal.signal !== "WAIT" },
        { name: "orderflow_confirmation", passed: signal.signal !== "WAIT" },
      ],
    },
    confirmation: buildDemoMultiTimeframe(signal).confirmation,
    trade_plan: signal.trade_plan,
    trade_plan_validation: { is_valid: signal.signal !== "WAIT", errors: [] },
    timeframes: [],
    prediction_stack: ["1h", "2h", "4h", "1d"],
    entry_stack: [],
    timing_stack: [],
  };
}

function buildDemoOpenTrades(signal, priceMap) {
  const demoSymbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"];
  return demoSymbols.map((item, index) => {
    const entry = priceMap[item] * (1 - index * 0.004);
    const current = priceMap[item];
    return {
      id: `open-${item}`,
      symbol: item,
      side: index % 2 === 0 ? "LONG" : "SHORT",
      entry_price: roundPrice(entry),
      current_price: roundPrice(current),
      unrealized_pnl_percent: index % 2 === 0 ? roundPrice(((current - entry) / entry) * 100) : roundPrice(((entry - current) / entry) * 100),
      source_signal: signal.signal,
    };
  });
}

function buildDemoClosedTrades() {
  const trades = [
    { symbol: "BTCUSDT", side: "LONG", entry: 64020, exit: 66540, pnl: 3.93, result: "WIN" },
    { symbol: "ETHUSDT", side: "SHORT", entry: 1825.2, exit: 1770.4, pnl: 3.00, result: "WIN" },
    { symbol: "XRPUSDT", side: "LONG", entry: 1.21, exit: 1.26, pnl: 4.13, result: "WIN" },
    { symbol: "SOLUSDT", side: "LONG", entry: 72.3, exit: 74.5, pnl: 3.04, result: "WIN" },
    { symbol: "BNBUSDT", side: "SHORT", entry: 622.1, exit: 613.4, pnl: 1.40, result: "WIN" },
    { symbol: "DOGEUSDT", side: "LONG", entry: 0.128, exit: 0.133, pnl: 3.91, result: "WIN" },
    { symbol: "BTCUSDT", side: "SHORT", entry: 67010, exit: 67420, pnl: -0.61, result: "LOSS" },
    { symbol: "ETHUSDT", side: "LONG", entry: 1792, exit: 1773, pnl: -1.06, result: "LOSS" },
  ];

  const now = Date.now();
  return trades.map((trade, index) => ({
    id: `closed-${index + 1}`,
    symbol: trade.symbol,
    side: trade.side,
    entry_price: trade.entry,
    exit_price: trade.exit,
    pnl_percent: trade.pnl,
    result: trade.result,
    status: "CLOSED",
    created_at: new Date(now - (index + 1) * 24 * 60 * 60 * 1000).toISOString(),
    closed_at: new Date(now - index * 20 * 60 * 1000).toISOString(),
  }));
}

function buildDemoPerformance(openTrades, closedTrades) {
  const wins = closedTrades.filter((trade) => safeNumber(trade.pnl_percent, 0) > 0).length;
  const losses = closedTrades.filter((trade) => safeNumber(trade.pnl_percent, 0) < 0).length;
  const total = closedTrades.length + openTrades.length;
  const closedTotal = closedTrades.reduce((sum, trade) => sum + safeNumber(trade.pnl_percent, 0), 0);
  return {
    total_trades: total,
    open_trades: openTrades.length,
    closed_trades: closedTrades.length,
    wins,
    losses,
    long_trades: closedTrades.filter((trade) => trade.side === "LONG").length,
    short_trades: closedTrades.filter((trade) => trade.side === "SHORT").length,
    win_rate: total ? (wins / closedTrades.length) * 100 : 0,
    average_pnl_percent: closedTrades.length ? closedTotal / closedTrades.length : 0,
    total_pnl_percent: closedTotal,
  };
}
function signalType(signal) {
  const rawSignal = String(signal?.signal || "").toUpperCase();
  if (rawSignal === "LONG" || rawSignal === "BUY") return "BUY";
  if (rawSignal === "SHORT" || rawSignal === "SELL") return "SELL";
  if (rawSignal === "WAIT" || rawSignal === "NO_DATA") return "WAIT";

  const bias = String(signal?.bias || "").toUpperCase();
  if (bias.includes("LONG") && rawSignal !== "WAIT") return "BUY";
  if (bias.includes("SHORT") && rawSignal !== "WAIT") return "SELL";
  return "WAIT";
}

function roundPrice(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return 0;
  }
  return Number(number.toFixed(number >= 1 ? 2 : 5));
}

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}
