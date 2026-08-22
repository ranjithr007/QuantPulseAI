import clsx from "clsx";
import {
  Activity,
  BarChart3,
  LineChart as LineChartIcon,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import MetricCard from "./ui/MetricCard";
import Pill from "./ui/Pill";
import Phase2ValidationBadge from "./Phase2ValidationBadge";
import { deriveSelectedEligibilityState } from "../utils/eligibility";
import { formatDate, formatInr, formatPercent, formatPrice, formatSigned, safeNumber, tooltipStyle } from "../utils/formatters";

const CHART_COLORS = ["#22d3ee", "#34d399", "#f59e0b", "#fb7185", "#a78bfa", "#60a5fa"];
const STAGED_EXIT_POLICIES = new Set(["PAPER_STAGED_EXIT_V2", "PAPER_STAGED_EXIT_V1", "BTC_1H_STAGED_V1"]);

export default function PnLSection({
  realizedPnl,
  unrealizedPnl,
  dailyPnl,
  weeklyPnl,
  monthlyPnl,
  maxDrawdown,
  winningTrades,
  losingTrades,
  winRate,
  tradeHistory,
  openPositions,
  paperWallet,
  pnlBySymbol,
  pnlBySide,
  equitySeries,
  auto,
  selectedDetail,
  autoDecision,
  selectedRisk,
  selectedPaperTradeCandidate,
}) {
  const totalTrades = tradeHistory.length + openPositions.length;
  const avgProfit = averagePnl(tradeHistory, true);
  const avgLoss = averagePnl(tradeHistory, false);
  const entryTrigger = selectedDetail?.timing?.trigger || selectedDetail?.entryTrigger?.trigger || selectedDetail?.timing || selectedDetail?.entryTrigger || null;
  const tradeSetup = selectedDetail?.prediction?.setup || selectedDetail?.tradeSetup?.setup || selectedDetail?.prediction || selectedDetail?.tradeSetup || null;
  const entryBand = entryTrigger?.confidence_window || tradeSetup?.confidence_window || null;
  const stackConfidence = entryTrigger?.stack_confidence ?? selectedDetail?.multiTimeframe?.confirmation?.stack_confidence ?? null;
  const predictionStack = selectedDetail?.predictionStack?.length ? selectedDetail.predictionStack.join(" / ") : selectedDetail?.multiTimeframe?.prediction_stack?.join(" / ") || "1h / 2h / 4h / 1d";
  const timingStack = selectedDetail?.timingStack?.length
    ? selectedDetail.timingStack.join(" / ")
    : selectedDetail?.multiTimeframe?.timing_stack?.join(" / ")
      || selectedDetail?.multiTimeframe?.entry_stack?.join(" / ")
      || "No lower-timeframe timing layer";
  const executionReason = entryTrigger?.reason || tradeSetup?.reason || "No execution reason available";
  const executionState = entryTrigger?.status || tradeSetup?.status || null;
  const eligibilityState = deriveSelectedEligibilityState({
    auto,
    autoDecision,
    selectedDetail,
    selectedRisk,
    openTrades: openPositions,
  });
  const executionPending = eligibilityState.label === "Ready to execute";
  const entryTriggerWaiting = executionState === "WAIT";
  const executor = executorState(selectedPaperTradeCandidate);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">PnL Dashboard</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Trade performance</h2>
            <div className="mt-1 text-xs text-slate-500">Futures paper evidence · official entry stack 1h / 2h / 4h / 1d</div>
          </div>
        </div>

        <PaperWalletStrip wallet={paperWallet} openPositions={openPositions} />

        {selectedDetail ? (
          <div
            className={clsx(
              "mt-3 rounded-lg border px-3 py-2.5",
              entryTriggerWaiting
                ? "border-amber-400/20 bg-amber-500/10 text-amber-100"
                : "border-emerald-400/20 bg-emerald-500/10 text-emerald-100"
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-medium">
                {selectedDetail.symbol || "Selected contract"}{" "}
                {executor.label === "Executor blocked"
                  ? "is blocked by the paper-trade executor"
                  : executionPending
                  ? "is eligible and waiting for futures paper-trade execution"
                  : entryTriggerWaiting
                    ? "is waiting for timing confirmation"
                    : "is execution-ready"}
              </div>
              <Pill tone={executor.tone === "rose" ? "rose" : executionPending ? "amber" : entryTriggerWaiting ? "amber" : "emerald"}>
                {executor.label === "Executor blocked" ? executor.label : executionPending ? "READY" : executionState || autoDecision?.stackState || "UNKNOWN"}
              </Pill>
            </div>
            <div className="mt-1.5 text-xs leading-5 opacity-90">
              {executor.label === "Executor blocked"
                ? executor.note
                : executionPending
                  ? "The risk gate passed, but no futures paper trade has been opened yet."
                  : executionReason}
            </div>
            {selectedPaperTradeCandidate?.blocked_reasons?.length ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {selectedPaperTradeCandidate.blocked_reasons.map((reason) => (
                  <Pill key={reason} tone="rose">{reason}</Pill>
                ))}
              </div>
            ) : null}
            {entryBand ? (
              <div className="mt-1 text-[11px] opacity-80">
                Entry band: {entryBand.min}% - {entryBand.max}% confidence, preferred {entryBand.preferred}%
              </div>
            ) : null}
            {stackConfidence !== null && stackConfidence !== undefined ? (
              <div className="mt-0.5 text-[11px] opacity-70">Stack confidence: {Number(stackConfidence).toFixed(2)}%</div>
            ) : null}
            <div className="mt-0.5 text-[11px] opacity-70">Prediction stack: {predictionStack}</div>
            <div className="mt-0.5 text-[11px] opacity-70">Timing stack: {timingStack}</div>
            {entryTrigger?.conditions?.length ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {entryTrigger.conditions.map((condition) => (
                  <Pill key={condition.name} tone={condition.passed ? "emerald" : "rose"}>
                    {condition.name}: {condition.passed ? "PASS" : "WAIT"}
                  </Pill>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="mt-3">
          <Phase2ValidationBadge
            symbol={selectedDetail?.symbol}
            timeframe={selectedDetail?.timeframe || "1h"}
            signalType={selectedDetail?.signalType}
          />
        </div>

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-6">
          <MetricCard label="Total unrealized PnL" value={formatSigned(unrealizedPnl)} note="Open PnL" icon={TrendingUp} accent="emerald" />
          <MetricCard label="Total realized PnL" value={formatSigned(realizedPnl)} note="Closed PnL" icon={TrendingDown} accent="rose" />
          <MetricCard label="Daily PnL" value={formatSigned(dailyPnl)} note="Closed trades" icon={Activity} accent="cyan" />
          <MetricCard label="Weekly PnL" value={formatSigned(weeklyPnl)} note="Closed trades" icon={LineChartIcon} accent="amber" />
          <MetricCard label="Monthly PnL" value={formatSigned(monthlyPnl)} note="Closed trades" icon={BarChart3} accent="violet" />
          <MetricCard label="Win rate" value={formatPercent(winRate)} note={`${winningTrades} wins / ${losingTrades} losses`} icon={ShieldCheck} accent="emerald" />
        </div>

        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Total trades" value={totalTrades} note="Open + closed" icon={Wallet} accent="cyan" compact />
          <MetricCard label="Winning trades" value={winningTrades} note="Closed trades" icon={ShieldCheck} accent="emerald" compact />
          <MetricCard label="Losing trades" value={losingTrades} note="Closed trades" icon={ShieldAlert} accent="rose" compact />
          <MetricCard label="Avg profit / loss" value={`${formatSigned(avgProfit)} / ${formatSigned(avgLoss)}`} note="Closed samples" icon={BarChart3} accent="amber" compact />
        </div>

        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-2">
          <DiagnosticStrip
            label="Executor truth"
            value={executor.label}
            note={executor.note}
            tone={executor.tone}
          />
          <DiagnosticStrip
            label="Eligibility"
            value={eligibilityState.label}
            note={eligibilityState.note}
            tone={eligibilityState.tone}
          />
          <DiagnosticStrip
            label="Top block"
            value={topReasonLabel(autoDecision?.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
            note={topReasonNote(autoDecision?.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
            tone={topReasonTone(autoDecision?.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
          />
          <DiagnosticStrip
            label="Timing state"
            value={executionState || "UNKNOWN"}
            note={executionReason}
            tone={timingTone(executionState)}
          />
        </div>

        <div className="mt-3">
          <LifecyclePanel
            stages={paperTradeLifecycle({
              symbol: selectedDetail?.symbol,
              eligibilityState,
              selectedPaperTradeCandidate,
              openPositions,
              tradeHistory,
            })}
          />
        </div>

        <div className="mt-3.5 grid items-start gap-3.5 xl:grid-cols-[1.35fr_0.65fr]">
          <div className="min-w-0 rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">Equity curve</div>
                <div className="text-xs text-slate-500">Cumulative closed trade PnL</div>
              </div>
              <Pill tone="cyan">{formatSigned(maxDrawdown)} max drawdown</Pill>
            </div>
            <div className="h-60 min-w-0 w-full">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 720, height: 240 }}>
                <AreaChart data={equitySeries}>
                  <defs>
                    <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#22d3ee" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <Tooltip contentStyle={tooltipStyle()} />
                  <Area type="monotone" dataKey="equity" stroke="#22d3ee" fill="url(#equityFill)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="min-w-0 rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">PnL mix</div>
                <div className="text-xs text-slate-500">Closed trades by signal type</div>
              </div>
              <Pill tone="slate">{tradeHistory.length} closed</Pill>
            </div>
            <div className="h-36 min-w-0 w-full">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 420, height: 144 }}>
                <PieChart>
                  <Pie data={pnlBySide} dataKey="value" nameKey="name" innerRadius={35} outerRadius={65}>
                    {pnlBySide.map((entry, index) => (
                      <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => [formatSigned(value), "PnL"]} contentStyle={tooltipStyle()} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-2 space-y-1.5">
              {pnlBySide.map((item, index) => (
                <div key={item.name} className="flex items-center justify-between rounded-lg border border-white/10 bg-slate-950/70 px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }} />
                    <span className="text-sm text-slate-300">{item.name}</span>
                  </div>
                  <span className="text-sm font-medium text-white">{formatSigned(item.value)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-3.5">
          <div className="min-w-0 rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">PNL by symbol</div>
                <div className="text-xs text-slate-500">Closed trade performance</div>
              </div>
            </div>
            <div className="h-60 min-w-0 w-full">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 560, height: 240 }}>
                <BarChart data={pnlBySymbol} layout="vertical">
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" horizontal={false} />
                  <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "#cbd5e1", fontSize: 11 }} width={80} />
                  <Tooltip formatter={(value) => [formatSigned(value), "PnL"]} contentStyle={tooltipStyle()} />
                  <Bar dataKey="value" radius={[0, 8, 8, 0]}>
                    {pnlBySymbol.map((entry, index) => (
                      <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="mt-3.5">
          <OpenPositionsTable openPositions={openPositions} />
        </div>

        <TradeHistoryTable tradeHistory={tradeHistory} />
      </div>
    </section>
  );
}

function executorState(candidate) {
  if (!candidate) {
    return {
      label: "No queued plan",
      note: "No OPEN trade plan is currently queued for the paper-trade executor on this symbol.",
      tone: "amber",
    };
  }

  if (candidate.eligible) {
    return {
      label: "Executor ready",
      note: "Queued OPEN trade plan passes executor checks.",
      tone: "emerald",
    };
  }

  return {
    label: "Executor blocked",
    note: candidate.blocked_reasons?.[0] || "Queued OPEN trade plan is blocked by executor checks.",
    tone: "rose",
  };
}

function DiagnosticStrip({ label, value, note, tone = "slate" }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
        <Pill tone={tone}>{value ?? "-"}</Pill>
      </div>
      <div className="mt-1.5 line-clamp-3 text-xs leading-5 text-slate-400" title={note || "-"}>{note || "-"}</div>
    </div>
  );
}

function LifecyclePanel({ stages = [] }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2.5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Paper-trade lifecycle</div>
          <div className="text-xs text-slate-500">From gate pass to queued candidate, opened trade, and closed result</div>
        </div>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3">
        {stages.map((stage) => (
          <div key={stage.key} className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{stage.label}</div>
              <Pill tone={stage.tone}>{stage.state}</Pill>
            </div>
            <div className="mt-1.5 line-clamp-3 text-xs leading-5 text-slate-400" title={stage.note}>{stage.note}</div>
            {stage.when ? <div className="mt-1 text-[11px] text-slate-500">{stage.when}</div> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function topReasonLabel(riskReasons = [], executorReasons = []) {
  const reason = (riskReasons && riskReasons[0]) || (executorReasons && executorReasons[0]);
  return reason || "No active blocks";
}

function topReasonNote(riskReasons = [], executorReasons = []) {
  if (riskReasons?.length) return `Risk/auto rules report ${riskReasons.length} active block(s)`;
  if (executorReasons?.length) return `Executor reports ${executorReasons.length} active block(s)`;
  return "No active risk or executor blocks";
}

function topReasonTone(riskReasons = [], executorReasons = []) {
  if (riskReasons?.length || executorReasons?.length) return "rose";
  return "emerald";
}

function timingTone(status) {
  const value = String(status || "").toUpperCase();
  if (value === "READY" || value === "TRIGGERED" || value === "ACTIVE") return "emerald";
  if (value === "WAIT") return "amber";
  return "slate";
}

function paperTradeLifecycle({ symbol, eligibilityState, selectedPaperTradeCandidate, openPositions = [], tradeHistory = [] }) {
  const normalizedSymbol = String(symbol || "").toUpperCase();
  const selectedOpenTrade = openPositions.find((trade) => String(trade?.symbol || "").toUpperCase() === normalizedSymbol);
  const selectedClosedTrade = tradeHistory.find((trade) => String(trade?.symbol || "").toUpperCase() === normalizedSymbol);
  const eligible = ["Eligible", "Ready to execute"].includes(String(eligibilityState?.label || ""));
  const candidateExists = Boolean(selectedPaperTradeCandidate);
  const executorReady = Boolean(selectedPaperTradeCandidate?.eligible);
  const openNow = Boolean(selectedOpenTrade);
  const closedSeen = Boolean(selectedClosedTrade);
  const queuedAt = selectedPaperTradeCandidate?.trade_plan?.created_at || null;
  const executorCheckedAt = selectedPaperTradeCandidate?.risk_decision?.created_at || queuedAt || null;
  const openedAt = selectedOpenTrade?.opened_at || selectedOpenTrade?.created_at || null;
  const closedAt = selectedClosedTrade?.closed_at || selectedClosedTrade?.created_at || null;
  const riskFreshness = selectedPaperTradeCandidate?.risk_decision?.freshness || null;
  const riskStale = Boolean(riskFreshness?.is_stale);
  const staleNote = staleFreshnessNote(riskFreshness, "Risk decision");

  return [
    {
      key: "eligible",
      label: "1. Eligible",
      state: eligible ? (riskStale ? "Stale" : "Done") : "Blocked",
      tone: eligible ? (riskStale ? "amber" : "emerald") : "rose",
      note: eligible
        ? (riskStale ? `Signal passed earlier, but ${staleNote}.` : "Signal passed the current auto/risk gate.")
        : (eligibilityState?.note || "Signal has not passed the gate."),
      when: stageTimestampLabel(executorCheckedAt || queuedAt),
    },
    {
      key: "queued",
      label: "2. Queued",
      state: candidateExists ? (riskStale && !openNow ? "Stale" : "Done") : "Waiting",
      tone: candidateExists ? (riskStale && !openNow ? "amber" : "emerald") : "amber",
      note: candidateExists
        ? (riskStale && !openNow ? `An OPEN paper-trade candidate exists, but ${staleNote}.` : "An OPEN paper-trade candidate exists for this symbol/side.")
        : "No OPEN paper-trade candidate is queued yet.",
      when: stageTimestampLabel(queuedAt),
    },
    {
      key: "executor",
      label: "3. Executor ready",
      state: executorReady ? (riskStale ? "Stale risk" : "Done") : candidateExists ? (riskStale ? "Stale risk" : "Blocked") : "Waiting",
      tone: executorReady ? (riskStale ? "amber" : "emerald") : candidateExists ? (riskStale ? "amber" : "rose") : "amber",
      note: executorReady
        ? (riskStale ? `Queued candidate would be ready, but ${staleNote}.` : "Queued candidate passes executor checks.")
        : candidateExists
          ? (riskStale ? "Executor needs a fresh risk decision before treating this candidate as ready." : (selectedPaperTradeCandidate?.blocked_reasons?.[0] || "Queued candidate is blocked by executor checks."))
          : "Executor has nothing to evaluate yet.",
      when: stageTimestampLabel(executorCheckedAt),
    },
    {
      key: "opened",
      label: "4. Opened",
      state: openNow ? "Live" : "Waiting",
      tone: openNow ? "cyan" : "amber",
      note: openNow ? "A futures paper trade is currently open for this symbol." : "No open futures paper trade is active for this symbol.",
      when: stageTimestampLabel(openedAt),
    },
    {
      key: "closed",
      label: "5. Closed",
      state: closedSeen ? "Done" : "Pending",
      tone: closedSeen ? "emerald" : "slate",
      note: closedSeen ? "At least one closed futures paper trade exists for this symbol." : "No closed futures paper trade has been recorded for this symbol yet.",
      when: stageTimestampLabel(closedAt),
    },
  ];
}

function stageTimestampLabel(value) {
  if (!value) return null;
  return `Updated ${formatDate(value)}`;
}

function staleFreshnessNote(freshness, label) {
  const ageSeconds = Number(freshness?.data_age_seconds);
  if (Number.isFinite(ageSeconds) && ageSeconds > 0) {
    return `${label.toLowerCase()} is stale (${formatAgeShort(ageSeconds)} old)`;
  }
  return `${label.toLowerCase()} is stale`;
}

function formatAgeShort(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  if (total < 60) return `${Math.round(total)}s`;
  if (total < 3600) return `${Math.round(total / 60)}m`;
  if (total < 86400) return `${Math.round(total / 3600)}h`;
  return `${Math.round(total / 86400)}d`;
}

function PaperWalletStrip({ wallet, openPositions }) {
  const capital = safeNumber(wallet?.paper_capital_inr, 100000);
  const committed = safeNumber(
    wallet?.committed_margin_inr,
    (openPositions || []).reduce(
      (sum, trade) => sum + safeNumber(trade?.paper_sizing?.remaining_margin_inr ?? trade?.margin_used_inr, 0),
      0
    )
  );
  const available = safeNumber(wallet?.available_margin_inr, Math.max(0, capital - committed));
  const utilization = capital > 0 ? (committed / capital) * 100 : 0;

  return (
    <div className="mt-3 grid gap-2 rounded-lg border border-cyan-400/20 bg-cyan-500/5 p-3 sm:grid-cols-4">
      <WalletDatum label="INR-M paper wallet" value={formatInr(capital)} note="Paper trading only" />
      <WalletDatum label="Committed margin" value={formatInr(committed)} note={`${formatPercent(utilization, 1)} utilised`} />
      <WalletDatum label="Available balance" value={formatInr(available)} note="Uncommitted paper capital" />
      <WalletDatum label="Position sizing" value="75% / 85%" note={`${formatInr(75000)} minimum / ${formatInr(85000)} maximum notional`} />
    </div>
  );
}

function WalletDatum({ label, value, note }) {
  return (
    <div className="rounded-md border border-white/5 bg-slate-950/35 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-white">{value}</div>
      <div className="mt-0.5 text-[10px] text-slate-500">{note}</div>
    </div>
  );
}

function OpenPositionsTable({ openPositions }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Open positions</div>
          <div className="text-xs text-slate-500">All current open futures paper trades across the account</div>
        </div>
        <Pill tone="cyan">{openPositions.length} open</Pill>
      </div>
      <div className="overflow-x-auto rounded-lg border border-white/10">
        <table className="min-w-[1320px] w-full divide-y divide-white/5 text-sm">
          <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            <tr>
              <th className="px-3 py-2.5 text-left">Symbol</th>
              <th className="px-3 py-2.5 text-left">Timeframe</th>
              <th className="px-3 py-2.5 text-left">Side</th>
              <th className="px-3 py-2.5 text-left">INR position</th>
              <th className="px-3 py-2.5 text-left">Entry</th>
              <th className="px-3 py-2.5 text-left">Stop-loss</th>
              <th className="px-3 py-2.5 text-left">Target 1</th>
              <th className="px-3 py-2.5 text-left">Target 2</th>
              <th className="px-3 py-2.5 text-left">Remaining</th>
              <th className="px-3 py-2.5 text-left">Exit state</th>
              <th className="px-3 py-2.5 text-left">Deadline</th>
              <th className="px-3 py-2.5 text-left">Current</th>
              <th className="px-3 py-2.5 text-left">PnL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {openPositions.map((trade) => (
              <tr key={trade.id} className="bg-slate-950/40">
                <td className="px-3 py-2.5 text-white">{trade.symbol}</td>
                <td className="px-3 py-2.5 text-slate-300">{trade.entry_timeframe || "-"}</td>
                <td className="px-3 py-2.5">
                  <Pill tone={trade.side === "LONG" ? "emerald" : "rose"}>{trade.side}</Pill>
                </td>
                <td className="px-3 py-2.5 text-slate-200">
                  <div>{formatInr(trade?.paper_sizing?.position_notional_inr ?? trade?.position_notional_inr)}</div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    Margin {formatInr(trade?.paper_sizing?.remaining_margin_inr ?? trade?.margin_used_inr)} / {safeNumber(trade?.paper_sizing?.leverage ?? trade?.leverage, 5)}x
                  </div>
                </td>
                <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.entry_price)}</td>
                <td className="px-3 py-2.5 text-rose-200">
                  <div>{formatPrice(trade.stop_loss)}</div>
                  {stopProtectionLabel(trade) ? <div className="mt-0.5 text-[10px] uppercase tracking-wide text-emerald-300">{stopProtectionLabel(trade)}</div> : null}
                </td>
                <td className={clsx("px-3 py-2.5", trade.target1_hit_at ? "text-emerald-300" : "text-slate-300")}>
                  <div>{formatPrice(trade.target1)}</div>
                  {trade.target1_hit_at ? <div className="mt-0.5 text-[10px] uppercase tracking-wide">Completed</div> : null}
                </td>
                <td className="px-3 py-2.5 text-emerald-200">{formatPrice(trade.target2)}</td>
                <td className="px-3 py-2.5 text-slate-300">{remainingPositionLabel(trade)}</td>
                <td className="px-3 py-2.5">
                  <Pill tone={exitState(trade).tone}>{exitState(trade).label}</Pill>
                  <div className="mt-1 text-[10px] text-slate-500">{exitPolicyLabel(trade)}</div>
                </td>
                <td className="px-3 py-2.5 text-slate-400">
                  <div>{exitDeadlineLabel(trade)}</div>
                  <div className="mt-0.5 text-[10px] text-slate-500">{exitTimeRemainingLabel(trade)}</div>
                </td>
                <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.current_price)}</td>
                <td className={clsx("px-3 py-2.5 font-medium", trade.unrealized_pnl_percent >= 0 ? "text-emerald-300" : "text-rose-300")}>
                  {formatSigned(trade.unrealized_pnl_percent)}
                </td>
              </tr>
            ))}
            {!openPositions.length ? (
              <tr>
                <td className="px-3 py-3.5 text-slate-400" colSpan={13}>
                  No open paper positions.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function stopProtectionLabel(trade) {
  if (!trade?.target1_hit_at) return null;
  const entry = Number(trade.entry_price);
  const stop = Number(trade.stop_loss);
  const target1 = Number(trade.target1);
  if (!Number.isFinite(entry) || !Number.isFinite(stop)) return null;
  const tolerance = Math.max(1e-8, Math.abs(entry) * 1e-8);
  if (Number.isFinite(target1) && Math.abs(target1 - stop) <= tolerance) return "Target 1 protected";
  if (Math.abs(entry - stop) <= tolerance) return "Break-even";
  const profitProtected = trade.side === "LONG" ? stop > entry : stop < entry;
  return profitProtected ? "Profit protected" : null;
}

function remainingPositionLabel(trade) {
  const rawRemaining = trade?.remaining_position_fraction;
  if (rawRemaining === null || rawRemaining === undefined || rawRemaining === "") return "100%";
  const remaining = Number(rawRemaining);
  return Number.isFinite(remaining) ? `${Math.round(remaining * 100)}%` : "100%";
}

function exitState(trade) {
  if (isStagedExitPolicy(trade)) {
    if (trade.target1_hit_at) {
      return { label: "Awaiting T2", tone: "cyan" };
    }
    return { label: "Awaiting T1", tone: "amber" };
  }
  return { label: "Standard exit", tone: "slate" };
}

function exitPolicyLabel(trade) {
  if (isStagedExitPolicy(trade)) return "T1 closes 75% / protected stop / T2 closes 25%";
  return "Original trade policy";
}

function isStagedExitPolicy(trade) {
  return STAGED_EXIT_POLICIES.has(String(trade?.exit_policy || "").toUpperCase());
}

function exitDeadline(trade) {
  const openedAt = Date.parse(trade?.opened_at || trade?.created_at || "");
  const maxHoldHours = Number(trade?.max_hold_hours);
  if (!Number.isFinite(openedAt) || !Number.isFinite(maxHoldHours) || maxHoldHours <= 0) return null;
  return openedAt + maxHoldHours * 60 * 60 * 1000;
}

function exitDeadlineLabel(trade) {
  const deadline = exitDeadline(trade);
  return deadline === null ? "No fixed deadline" : formatDate(new Date(deadline).toISOString());
}

function exitTimeRemainingLabel(trade) {
  const deadline = exitDeadline(trade);
  if (deadline === null) return "Original policy";
  const remainingMs = deadline - Date.now();
  if (remainingMs <= 0) return "Time exit due";
  const hours = Math.ceil(remainingMs / (60 * 60 * 1000));
  return `${hours}h remaining`;
}

function TradeHistoryTable({ tradeHistory }) {
  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Trade history</div>
          <div className="text-xs text-slate-500">All closed futures paper trades across the account</div>
        </div>
        <Pill tone="slate">{tradeHistory.length} closed</Pill>
      </div>
      <div className="mt-2.5 overflow-x-auto">
        <table className="min-w-full divide-y divide-white/5 text-sm">
          <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            <tr>
              <th className="px-3 py-2.5 text-left">Symbol</th>
              <th className="px-3 py-2.5 text-left">Side</th>
              <th className="px-3 py-2.5 text-left">Entry</th>
              <th className="px-3 py-2.5 text-left">Exit</th>
              <th className="px-3 py-2.5 text-left">PnL</th>
              <th className="px-3 py-2.5 text-left">Result</th>
              <th className="px-3 py-2.5 text-left">Closed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {tradeHistory.map((trade) => (
              <tr key={trade.id} className="bg-slate-950/35">
                <td className="px-3 py-2.5 text-white">{trade.symbol}</td>
                <td className="px-3 py-2.5">
                  <Pill tone={trade.side === "LONG" ? "emerald" : "rose"}>{trade.side}</Pill>
                </td>
                <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.entry_price)}</td>
                <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.exit_price)}</td>
                <td className={clsx("px-3 py-2.5 font-medium", safeNumber(trade.pnl_percent, 0) >= 0 ? "text-emerald-300" : "text-rose-300")}>
                  {formatSigned(trade.pnl_percent)}
                </td>
                <td className="px-3 py-2.5 text-slate-300">{trade.result || "N/A"}</td>
                <td className="px-3 py-2.5 text-slate-400">{formatDate(trade.closed_at || trade.created_at)}</td>
              </tr>
            ))}
            {!tradeHistory.length ? (
              <tr>
                <td className="px-3 py-3.5 text-slate-400" colSpan={7}>
                  No closed trades available.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function averagePnl(trades, positive) {
  const items = trades.filter((trade) => (safeNumber(trade.pnl_percent, 0) > 0) === positive);
  if (!items.length) return 0;
  return Number((items.reduce((sum, trade) => sum + safeNumber(trade.pnl_percent, 0), 0) / items.length).toFixed(2));
}
