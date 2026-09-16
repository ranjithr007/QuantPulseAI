import clsx from "clsx";
import ExitPolicyEvidence from "./ExitPolicyEvidence";
import PaperTradeHistory from "./PaperTradeHistory";
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
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import MetricCard from "./ui/MetricCard";
import Pill from "./ui/Pill";
import Phase2ValidationBadge from "./Phase2ValidationBadge";
import { deriveSelectedEligibilityState } from "../utils/eligibility";
import {
  candidateExecutorBlockers,
  executorStrategyLabel,
  isCandidateExecutorReady,
} from "../utils/executorCompetition";
import { formatDate, formatInr, formatPercent, formatPrice, formatSigned, safeNumber, timestampMillis, tooltipStyle } from "../utils/formatters";

const STAGED_EXIT_POLICIES = new Set(["PAPER_ATR_STRUCTURE_V1", "PAPER_STAGED_EXIT_V2", "PAPER_STAGED_EXIT_V1", "BTC_1H_STAGED_V1"]);

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
  averageProfit,
  averageLoss,
  averagePnlScope,
  performanceHealth,
  tradeHistory,
  closedTradeCount,
  openPositions,
  paperWallet,
  ledgerScope,
  headlineMeasurement,
  cleanPerformance,
  confidenceCalibration,
  returnDecomposition,
  measurementEvaluation,
  measurementDataQuality,
  exitClassificationCohorts,
  operationalExitQuality,
  operationalExitQualityError,
  pnlBySymbol,
  pnlBySide,
  pnlBreakdownScope,
  pnlCohorts,
  equitySeries,
  equityCurveMeta,
  auto,
  selectedDetail,
  autoDecision,
  selectedRisk,
  selectedPaperTradeCandidate,
}) {
  const accountLedgerPending = !ledgerScope || ledgerScope.symbol_filter !== null;
  const totalTrades = (closedTradeCount ?? tradeHistory.length) + openPositions.length;
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
  const eligibilityBlocked = !["Eligible", "Ready to execute"].includes(eligibilityState.label);
  const entryTriggerWaiting = executionState === "WAIT";
  const executor = executorState(selectedPaperTradeCandidate);
  const exactEquityCurve = equityCurveMeta?.scope === "PAPER_PRODUCTION_REALIZED_LEDGER";

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

        {accountLedgerPending ? <PnlLedgerLoading /> : null}

        {Number(ledgerScope?.quarantined_records || 0) > 0 ? (
          <div className="mt-3 rounded-lg border border-cyan-400/20 bg-cyan-500/10 px-3 py-2.5 text-sm text-cyan-100">
            <span className="font-medium">QA evidence quarantined:</span>{" "}
            {ledgerScope.quarantined_records} synthetic record(s) are preserved for audit but excluded from PNL, wallet, risk limits, and execution capacity.
          </div>
        ) : null}

        {paperWallet?.entry_protection?.new_entries_paused ? (
          <div className="mt-3 rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2.5 text-sm text-rose-100" role="alert">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">New official paper entries paused</span>
              <Pill tone="rose">PORTFOLIO SAFETY</Pill>
            </div>
            <div className="mt-1 text-xs leading-5 text-rose-200/85">
              Marked-equity drawdown is {formatPercent(paperWallet.entry_protection.drawdown_percent, 2)}; the safety limit is {formatPercent(paperWallet.entry_protection.limit_percent, 2)}. Existing positions remain under normal exit monitoring.
            </div>
          </div>
        ) : null}

        {paperWallet?.exit_protection?.ready === false ? (
          <div className="mt-3 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-100" role="alert">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">New entries blocked: exit protection unavailable</span>
              <Pill tone="amber">FAST EXIT SAFETY</Pill>
            </div>
            <div className="mt-1 text-xs leading-5 text-amber-200/85">
              {paperWallet.exit_protection.reason || "The one-second exit worker is not ready."} Existing positions remain monitored when the worker recovers.
            </div>
          </div>
        ) : null}

        {operationalExitQualityError ? (
          <div className="mt-3 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-100" role="alert">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">Exit-data quality unavailable</span>
              <Pill tone="amber">AUDIT UNAVAILABLE</Pill>
            </div>
            <div className="mt-1 text-xs leading-5 text-amber-200/85">
              {operationalExitQualityError}. Positions, wallet, performance, and trade history continue to load independently.
            </div>
          </div>
        ) : null}

        {Number(operationalExitQuality?.late_time_exits || 0) > 0 || Number(operationalExitQuality?.stale_recorded_exit_triggers || 0) > 0 ? (
          <div className="mt-3 rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2.5 text-sm text-rose-100" role="alert">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">Historical PNL contains operationally delayed exits</span>
              <Pill tone="rose">EXIT DATA QUALITY</Pill>
            </div>
            <div className="mt-1 text-xs leading-5 text-rose-200/85">
              {Number(operationalExitQuality.late_time_exits || 0) > 0 ? `${operationalExitQuality.late_time_exits} of ${operationalExitQuality.time_exits || operationalExitQuality.closed_trades || 0} recorded time exits breached their deadline by more than ${formatDurationMinutes(operationalExitQuality.deadline_grace_minutes)}. The longest delay was ${formatDurationMinutes(operationalExitQuality.maximum_exit_delay_minutes)}, and the affected trades contributed ${formatSigned(operationalExitQuality.late_time_exit_net_pnl_percent)}% to the closed-trade return sum.` : ""}
              {Number(operationalExitQuality.stale_recorded_exit_triggers || 0) > 0 ? ` ${operationalExitQuality.stale_recorded_exit_triggers} recorded trigger(s) exceeded the ${operationalExitQuality.maximum_promotion_quote_age_seconds}s promotion-quality limit; the largest observation delay was ${operationalExitQuality.maximum_recorded_trigger_quote_age_seconds}s.` : ""}
              {" These operationally contaminated outcomes remain included in headline PNL for audit continuity, but are excluded from clean strategy evidence."}
            </div>
          </div>
        ) : null}

        {paperWallet ? <PaperWalletStrip wallet={paperWallet} openPositions={openPositions} /> : null}

        {performanceHealth ? <HistoricalEdgeHealth health={performanceHealth} /> : null}

        {headlineMeasurement && cleanPerformance ? (
          <CleanEvidenceComparison
            headline={headlineMeasurement}
            clean={cleanPerformance}
            evaluation={measurementEvaluation}
          />
        ) : null}

        {confidenceCalibration ? (
          <ConfidenceCalibration evidence={confidenceCalibration} />
        ) : null}

        {returnDecomposition ? (
          <ReturnDecomposition evidence={returnDecomposition} />
        ) : null}

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
                  : eligibilityBlocked
                    ? "is not eligible for a new paper trade"
                  : entryTriggerWaiting
                    ? "is waiting for timing confirmation"
                    : executionState
                      ? "is execution-ready"
                      : "is eligible under the current paper-trade rules"}
              </div>
              <Pill tone={executor.tone === "rose" || eligibilityBlocked ? "rose" : executionPending || entryTriggerWaiting ? "amber" : "emerald"}>
                {executor.label === "Executor blocked"
                  ? executor.label
                  : executionPending
                    ? "READY"
                    : eligibilityBlocked
                      ? "BLOCKED"
                      : executionState || autoDecision?.stackState || "ELIGIBLE"}
              </Pill>
            </div>
            <div className="mt-1.5 text-xs leading-5 opacity-90">
              {executor.label === "Executor blocked"
                ? executor.note
                : executionPending
                  ? "The risk gate passed, but no futures paper trade has been opened yet."
                  : eligibilityBlocked
                    ? eligibilityState.note
                    : executionReason}
            </div>
            {candidateExecutorBlockers(selectedPaperTradeCandidate).length ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {candidateExecutorBlockers(selectedPaperTradeCandidate).map((reason) => (
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
          <MetricCard label="Open trade return sum" value={`${formatSigned(unrealizedPnl)}%`} note="Sum of trade returns, not account return" icon={TrendingUp} accent="emerald" />
          <MetricCard label="Closed trade return sum" value={`${formatSigned(realizedPnl)}%`} note="Sum of trade returns, not account return" icon={TrendingDown} accent="rose" />
          <MetricCard label="24h trade return sum" value={`${formatSigned(dailyPnl)}%`} note="Rolling 24 hours, not the IST calendar day" icon={Activity} accent="cyan" />
          <MetricCard label="7d trade return sum" value={`${formatSigned(weeklyPnl)}%`} note="Rolling 7 days, not account return" icon={LineChartIcon} accent="amber" />
          <MetricCard label="30d trade return sum" value={`${formatSigned(monthlyPnl)}%`} note="Rolling 30 days, not account return" icon={BarChart3} accent="violet" />
          <MetricCard label="Win rate" value={formatPercent(winRate)} note={`${winningTrades} wins / ${losingTrades} losses`} icon={ShieldCheck} accent="emerald" />
        </div>

        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Total trades" value={totalTrades} note="Open + closed" icon={Wallet} accent="cyan" compact />
          <MetricCard label="Profit factor" value={formatRatio(performanceHealth?.profit_factor)} note="Gross winning return ÷ gross losing return" icon={ShieldCheck} accent={performanceHealth?.status === "POSITIVE" ? "emerald" : "rose"} compact />
          <MetricCard label="Payoff ratio" value={formatRatio(performanceHealth?.payoff_ratio)} note="Average winner ÷ average loser" icon={ShieldAlert} accent={safeNumber(performanceHealth?.payoff_ratio, 0) >= 1 ? "emerald" : "rose"} compact />
          <MetricCard label="Avg profit / loss" value={`${formatSigned(averageProfit)} / ${formatSigned(averageLoss)}`} note={averagePnlScope === "ALL_CLOSED_TRADES" ? `All ${closedTradeCount ?? 0} official closed trades` : `Loaded ${tradeHistory.length}-trade sample`} icon={BarChart3} accent="amber" compact />
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
            value={topReasonLabel(autoDecision?.reasons, candidateExecutorBlockers(selectedPaperTradeCandidate))}
            note={topReasonNote(autoDecision?.reasons, candidateExecutorBlockers(selectedPaperTradeCandidate))}
            tone={topReasonTone(autoDecision?.reasons, candidateExecutorBlockers(selectedPaperTradeCandidate))}
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
                <div className="text-sm font-medium text-white">{exactEquityCurve ? "Realized wallet equity" : "Equity curve"}</div>
                <div className="text-xs text-slate-500">{exactEquityCurve ? `${equityCurveMeta.event_count} production ledger events${equityCurveMeta.downsampled ? ` · chart bounded to ${equityCurveMeta.point_count} points` : ""} · excludes open-position unrealized PNL` : `Loaded ${tradeHistory.length}-trade sample · cumulative trade percentages, not account return`}</div>
              </div>
              <Pill tone="cyan">{formatPercent(maxDrawdown, 2)} {exactEquityCurve ? "max realized drawdown" : "sample drawdown"}</Pill>
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
                  <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} tickFormatter={(value) => exactEquityCurve ? formatInr(value, 0) : value} width={exactEquityCurve ? 92 : 60} />
                  <Tooltip formatter={(value) => [exactEquityCurve ? formatInr(value, 2) : formatSigned(value), exactEquityCurve ? "Realized equity" : "Cumulative return"]} contentStyle={tooltipStyle()} />
                  <Area type="monotone" dataKey="equity" stroke="#22d3ee" fill="url(#equityFill)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="min-w-0 rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">PNL by side</div>
                <div className="text-xs text-slate-500">{pnlBreakdownScope === "ALL_CLOSED_TRADES" ? `All ${closedTradeCount ?? 0} official closed trades` : `Loaded ${tradeHistory.length}-trade sample`} · signed trade-return sums</div>
              </div>
              <Pill tone="slate">{pnlBreakdownScope === "ALL_CLOSED_TRADES" ? closedTradeCount : tradeHistory.length} closed</Pill>
            </div>
            <div className="h-36 min-w-0 w-full">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 420, height: 144 }}>
                <BarChart data={pnlBySide} layout="vertical">
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" horizontal={false} />
                  <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} width={54} />
                  <Tooltip formatter={(value) => [formatSigned(value), "PnL"]} contentStyle={tooltipStyle()} />
                  <Bar dataKey="value" radius={[6, 6, 6, 6]}>
                    {pnlBySide.map((entry) => (
                      <Cell key={entry.name} fill={pnlColor(entry.value)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-2 space-y-1.5">
              {pnlBySide.map((item) => (
                <div key={item.name} className="flex items-center justify-between rounded-lg border border-white/10 bg-slate-950/70 px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: pnlColor(item.value) }} />
                    <span className="text-sm text-slate-300">{item.name}</span>
                  </div>
                  <span className={clsx("text-sm font-medium", safeNumber(item.value, 0) >= 0 ? "text-emerald-300" : "text-rose-300")}>{formatSigned(item.value)}</span>
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
                <div className="text-xs text-slate-500">{pnlBreakdownScope === "ALL_CLOSED_TRADES" ? `All ${closedTradeCount ?? 0} official closed trades` : `Loaded ${tradeHistory.length}-trade sample`} · signed trade-return sums, not account return</div>
              </div>
            </div>
            <div className="h-60 min-w-0 w-full">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 560, height: 240 }}>
                <BarChart data={pnlBySymbol} layout="vertical">
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" horizontal={false} />
                  <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "#475569", fontSize: 11 }} width={80} />
                  <Tooltip formatter={(value) => [formatSigned(value), "PnL"]} contentStyle={tooltipStyle()} />
                  <Bar dataKey="value" radius={[0, 8, 8, 0]}>
                    {pnlBySymbol.map((entry) => (
                      <Cell key={entry.name} fill={pnlColor(entry.value)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {pnlCohorts?.scope === "ALL_OFFICIAL_CLOSED_TRADES" ? (
          <PnlCohortDiagnostics breakdown={pnlCohorts} />
        ) : null}

        {exitClassificationCohorts?.length ? (
          <ExitClassificationDiagnostics
            records={exitClassificationCohorts}
            missingActivationCount={measurementDataQuality?.closed_trades_missing_trailing_activation}
          />
        ) : null}

        <div className="mt-3.5">
          <OpenPositionsTable openPositions={openPositions} />
        </div>

        <PaperTradeHistory tradeHistory={tradeHistory} totalCount={closedTradeCount} />
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

  if (isCandidateExecutorReady(candidate)) {
    return {
      label: "Executor ready",
      note: `${executorStrategyLabel(candidate)} is the selected official paper strategy.`,
      tone: "emerald",
    };
  }

  const blockers = candidateExecutorBlockers(candidate);
  return {
    label: "Executor blocked",
    note: blockers[0] || "Queued OPEN trade plan is blocked by executor checks.",
    tone: "rose",
  };
}

function HistoricalEdgeHealth({ health }) {
  const status = String(health?.status || "NO_CLOSED_TRADES").toUpperCase();
  const positive = status === "POSITIVE";
  const flat = status === "FLAT" || status === "NO_CLOSED_TRADES";
  const tone = positive ? "emerald" : flat ? "amber" : "rose";
  const title = positive
    ? "Historical paper-trading edge is positive"
    : flat
      ? "Historical paper-trading edge is not established"
      : "Historical paper-trading edge is negative";

  return (
    <div className={clsx(
      "mt-3 rounded-lg border px-3 py-2.5 text-sm",
      positive
        ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-100"
        : flat
          ? "border-amber-400/25 bg-amber-500/10 text-amber-100"
          : "border-rose-400/30 bg-rose-500/10 text-rose-100"
    )}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{title}</span>
        <Pill tone={tone}>{status.replaceAll("_", " ")}</Pill>
      </div>
      <div className="mt-1 text-xs leading-5 opacity-85">
        Profit factor {formatRatio(health.profit_factor)} · payoff ratio {formatRatio(health.payoff_ratio)} · profitable-trade rate {formatPercent(health.profitable_win_rate_percent, 2)} versus estimated break-even {formatPercent(health.breakeven_win_rate_percent, 2)} ({formatSigned(health.win_rate_gap_percent)} percentage points). Expectancy is {formatSigned(health.expectancy_percent)}% per official closed trade.
      </div>
    </div>
  );
}

function CleanEvidenceComparison({ headline, clean, evaluation }) {
  const excluded = Number(evaluation?.excluded_operationally_contaminated_exits || 0);
  const cleanNegative = safeNumber(clean?.expectancy_percent, 0) < 0;

  return (
    <div className="mt-3 rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-white">Headline versus clean strategy evidence</div>
          <div className="text-xs text-slate-500">Clean evidence excludes {excluded} operationally contaminated exit{excluded === 1 ? "" : "s"}; account PNL remains unchanged.</div>
        </div>
        <Pill tone={cleanNegative ? "rose" : "emerald"}>{cleanNegative ? "STILL NEGATIVE" : "POSITIVE"}</Pill>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <EvidenceMetric label="Headline return sum" value={`${formatSigned(headline.net_pnl_percent)}%`} note={`${headline.closed_trades || 0} official closed trades`} />
        <EvidenceMetric label="Clean return sum" value={`${formatSigned(clean.net_pnl_percent)}%`} note={`${clean.closed_trades || 0} clean closed trades`} />
        <EvidenceMetric label="Clean profit factor" value={formatRatio(clean.profit_factor)} note={`Headline ${formatRatio(headline.profit_factor)}`} />
        <EvidenceMetric label="Clean expectancy" value={`${formatSigned(clean.expectancy_percent)}%`} note={`Headline ${formatSigned(headline.expectancy_percent)}% per trade`} />
      </div>
      <div className={clsx("mt-2 text-xs leading-5", cleanNegative ? "text-rose-200/85" : "text-emerald-200/85")}>
        {cleanNegative
          ? "Delayed or stale exits explain part of the loss, but not all of it: clean strategy evidence remains negative."
          : "Clean operational evidence is positive, although the headline account ledger still includes every audited exit."}
      </div>
    </div>
  );
}

function EvidenceMetric({ label, value, note }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className="mt-1 text-base font-semibold text-white">{value}</div>
      <div className="mt-0.5 text-[11px] text-slate-500">{note}</div>
    </div>
  );
}

function ConfidenceCalibration({ evidence }) {
  const insufficient = evidence.status === "INSUFFICIENT_EVIDENCE";
  const aligned = evidence.status === "DIRECTIONALLY_ALIGNED";
  const higherUnderperforms = evidence.direction === "HIGHER_UNDERPERFORMS";
  const tone = aligned ? "emerald" : insufficient ? "amber" : "rose";
  const lower = evidence.below_60 || {};
  const higher = evidence.at_least_60 || {};

  return (
    <div className="mt-3 rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-white">Confidence calibration evidence</div>
          <div className="text-xs text-slate-500">Fixed score groups selected before reading outcomes · descriptive evidence, not threshold tuning</div>
        </div>
        <Pill tone={tone}>{String(evidence.status || "UNKNOWN").replaceAll("_", " ")}</Pill>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <EvidenceMetric label="Confidence below 60" value={`${formatSigned(lower.expectancy_percent)}%`} note={`${lower.closed_trades || 0} trades · ${formatPercent(lower.win_rate, 2)} win rate`} />
        <EvidenceMetric label="Confidence 60+" value={`${formatSigned(higher.expectancy_percent)}%`} note={`${higher.closed_trades || 0} trades · ${formatPercent(higher.win_rate, 2)} win rate`} />
        <EvidenceMetric label="Expectancy separation" value={`${formatSigned(evidence.expectancy_gap_percentage_points)} pp`} note="60+ expectancy minus below-60 expectancy" />
        <EvidenceMetric label="Score / PNL correlation" value={formatSigned(evidence.confidence_pnl_correlation, 3)} note={`${evidence.evaluated_trades || 0} measured closed trades`} />
      </div>
      <div className={clsx("mt-2 text-xs leading-5", aligned ? "text-emerald-200/85" : higherUnderperforms ? "text-rose-200/85" : "text-amber-200/85")}>
        {higherUnderperforms
          ? "Higher-confidence trades currently underperform the lower-confidence group. Confidence cannot justify promotion or larger sizing."
          : aligned
            ? "Higher-confidence trades are directionally better in this sample, but this association alone does not authorize promotion."
            : "The current sample does not demonstrate useful confidence separation."}
        {insufficient ? ` At least ${evidence.minimum_trades_per_group || 0} closed trades are required in each fixed group.` : ""}
      </div>
    </div>
  );
}

function ReturnDecomposition({ evidence }) {
  const complete = evidence.status === "COMPLETE";
  const preCostNegative = evidence.pre_cost_result === "NEGATIVE";

  return (
    <div className="mt-3 rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-white">Return and trading-cost decomposition</div>
          <div className="text-xs text-slate-500">Exact persisted components across {evidence.reconciled_trades || 0} of {evidence.closed_trades || 0} official closed trades</div>
        </div>
        <Pill tone={complete ? "cyan" : "amber"}>{complete ? "RECONCILED" : "INCOMPLETE"}</Pill>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <EvidenceMetric label="Post-fill gross return" value={`${formatSigned(evidence.post_fill_gross_return_percent)}%`} note="Price return after simulated slippage, before fees and funding" />
        <EvidenceMetric label="Trading fees" value={`−${formatUnsigned(evidence.fees_percent)}%`} note="Persisted round-trip fee drag" />
        <EvidenceMetric label="Funding cost" value={`${formatSigned(-safeNumber(evidence.funding_cost_percent, 0))}%`} note="Negative display means a cost; positive means a credit" />
        <EvidenceMetric label="Official net return" value={`${formatSigned(evidence.net_return_percent)}%`} note={`Reconciliation error ${formatSigned(evidence.reconciliation_error_percent, 4)}%`} />
      </div>
      <div className={clsx("mt-2 text-xs leading-5", preCostNegative ? "text-rose-200/85" : "text-amber-200/85")}>
        {preCostNegative
          ? `The strategy was already negative before fees and funding. Costs added ${formatPercent(evidence.total_cost_drag_percent, 2)} of drag, equal to ${formatPercent(evidence.cost_share_of_net_loss_percent, 2)} of the net loss.`
          : "The post-fill price result was not negative; review whether costs changed the final result sign."}
        {" Slippage is already embedded in the simulated fill prices and is not subtracted again."}
      </div>
    </div>
  );
}

function formatUnsigned(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.abs(number).toFixed(digits) : "N/A";
}

function ExitClassificationDiagnostics({ records, missingActivationCount }) {
  const sorted = [...records].sort(
    (left, right) => safeNumber(left.net_pnl_percent, 0) - safeNumber(right.net_pnl_percent, 0)
  );
  const total = sorted.reduce((sum, item) => sum + Number(item.closed_trades || 0), 0);

  return (
    <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-white">PNL by exact exit classification</div>
          <div className="text-xs text-slate-500">Recorded trigger evidence first, with persisted stop-level inference for legacy trades · all {total} official closed trades</div>
        </div>
        <Pill tone="slate">EXIT CAUSE</Pill>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {sorted.map((item) => (
          <div key={item.value} className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
            <div className="truncate text-[10px] uppercase tracking-[0.12em] text-slate-500" title={exitClassificationLabel(item.value)}>{exitClassificationLabel(item.value)}</div>
            <div className={clsx("mt-1 text-base font-semibold", pnlValueTone(item.net_pnl_percent))}>{formatSigned(item.net_pnl_percent)}%</div>
            <div className="mt-0.5 text-[11px] text-slate-500">{item.closed_trades || 0} trades · {item.wins || 0} profitable</div>
          </div>
        ))}
      </div>
      {Number(missingActivationCount || 0) > 0 ? (
        <div className="mt-2 text-xs leading-5 text-amber-200/85">
          {missingActivationCount} historical trade{Number(missingActivationCount) === 1 ? "" : "s"} lack an explicit trailing-activation value and retain the legacy immediate-trailing interpretation. New trades persist the activation policy explicitly.
        </div>
      ) : null}
    </div>
  );
}

function exitClassificationLabel(value) {
  return String(value || "UNKNOWN").replaceAll("_", " ");
}

function PnlCohortDiagnostics({ breakdown }) {
  const coverage = breakdown?.attribution_coverage || {};
  const total = Number(coverage.closed_trades || 0);
  const strategyCoverage = total ? (Number(coverage.strategy_attributed_trades || 0) / total) * 100 : 0;
  const regimeCoverage = total ? (Number(coverage.regime_attributed_trades || 0) / total) * 100 : 0;
  const cohorts = [
    ["Strategy", breakdown.by_strategy],
    ["Regime", breakdown.by_regime],
    ["Timeframe", breakdown.by_timeframe],
    ["Recorded exit trigger", breakdown.by_exit_reason],
  ];

  return (
    <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-white">Full-cohort PNL drivers</div>
          <div className="text-xs text-slate-500">Exact signed trade-return sums across all {total} official closed trades · strategy attribution {formatPercent(strategyCoverage, 1)} · regime attribution {formatPercent(regimeCoverage, 1)}</div>
        </div>
        <Pill tone="slate">RECORDED EVIDENCE</Pill>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {cohorts.map(([title, records]) => (
          <CohortPnlList key={title} title={title} records={records} />
        ))}
      </div>
    </div>
  );
}

function CohortPnlList({ title, records = [] }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/50 p-2.5">
      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">{title}</div>
      <div className="mt-2 space-y-1.5">
        {records.slice(0, 8).map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-3 text-xs">
            <span className="min-w-0 truncate text-slate-300" title={item.name}>{item.name}</span>
            <span className={clsx("shrink-0 font-medium", pnlValueTone(item.value))}>{formatSigned(item.value)}% · {item.closed_trades}</span>
          </div>
        ))}
        {!records.length ? <div className="text-xs text-slate-500">No attributed trades</div> : null}
      </div>
    </div>
  );
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
  const executorReady = isCandidateExecutorReady(selectedPaperTradeCandidate);
  const executorBlockers = candidateExecutorBlockers(selectedPaperTradeCandidate);
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
          ? (riskStale ? "Executor needs a fresh risk decision before treating this candidate as ready." : (executorBlockers[0] || "Queued candidate is blocked by executor checks."))
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

function formatDurationMinutes(value) {
  const minutes = Math.max(0, Number(value) || 0);
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 48) return `${hours.toFixed(hours < 10 ? 1 : 0)}h`;
  const days = hours / 24;
  return `${days.toFixed(days < 10 ? 1 : 0)}d`;
}

function PaperWalletStrip({ wallet, openPositions }) {
  const capital = safeNumber(wallet?.initial_capital_inr ?? wallet?.paper_capital_inr, 200000);
  const walletBalance = safeNumber(wallet?.wallet_balance_inr, capital);
  const unrealizedPnl = safeNumber(wallet?.unrealized_pnl_inr, 0);
  const equity = safeNumber(wallet?.equity_inr, walletBalance + unrealizedPnl);
  const realizedPnl = safeNumber(wallet?.realized_pnl_inr, walletBalance - capital);
  const committed = safeNumber(
    wallet?.committed_margin_inr,
    (openPositions || []).reduce(
      (sum, trade) => sum + safeNumber(trade?.paper_sizing?.remaining_margin_inr ?? trade?.margin_used_inr, 0),
      0
    )
  );
  const available = safeNumber(wallet?.available_margin_inr, Math.max(0, equity - committed));
  const utilization = equity > 0 ? (committed / equity) * 100 : 0;

  return (
    <div className="mt-3 grid gap-2 rounded-lg border border-cyan-400/20 bg-cyan-500/5 p-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      <WalletDatum label="Starting paper capital" value={formatInr(capital)} note="Fixed simulation baseline" />
      <WalletDatum label="Current wallet balance" value={formatInr(walletBalance)} note={`Realized PnL ${formatInr(realizedPnl)}`} />
      <WalletDatum label="Account equity" value={formatInr(equity)} note={`Includes open PnL ${formatInr(unrealizedPnl)}`} />
      <WalletDatum label="Committed margin" value={formatInr(committed)} note={`${formatPercent(utilization, 1)} utilised`} />
      <WalletDatum label="Available margin" value={formatInr(available)} note="Equity minus committed margin" />
      <WalletDatum label="New-entry risk budget" value="0.25% / 0.5% equity" note="Confidence 40–59 / 60+; wider stops reduce notional; capital and available-margin caps still apply" />
    </div>
  );
}

function PnlLedgerLoading() {
  return (
    <div className="mt-3 rounded-lg border border-cyan-400/20 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-100" role="status">
      <div className="font-medium">Loading the account-wide wallet summary...</div>
      <div className="mt-1 text-xs text-cyan-200/80">
        Open positions, performance, and trade history load independently and remain available while the wallet summary is pending.
      </div>
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
              <th className="px-3 py-2.5 text-left">Deadline (IST)</th>
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
                  <ExitPolicyEvidence trade={trade} />
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
                <td className={clsx("px-3 py-2.5", stopBoundaryCrossed(trade) ? "font-semibold text-rose-600" : "text-slate-300")}>
                  {formatPrice(trade.current_price)}
                </td>
                <td className={clsx("px-3 py-2.5 font-medium", pnlValueTone(trade.unrealized_pnl_percent))}>
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
  if (stopBoundaryCrossed(trade)) {
    return { label: "Exit processing", tone: "rose" };
  }
  if (isStagedExitPolicy(trade)) {
    if (trade.target1_hit_at) {
      return { label: "Awaiting T2", tone: "cyan" };
    }
    return { label: "Awaiting T1", tone: "amber" };
  }
  return { label: "Standard exit", tone: "slate" };
}

function exitPolicyLabel(trade) {
  if (stopBoundaryCrossed(trade)) return "Stop crossed; automatic exit pending";
  if (isStagedExitPolicy(trade)) return "T1 closes 75% / protected stop / T2 closes 25%";
  return "Original trade policy";
}

function stopBoundaryCrossed(trade) {
  const current = Number(trade?.current_price);
  const stop = Number(trade?.stop_loss);
  if (!Number.isFinite(current) || current <= 0 || !Number.isFinite(stop) || stop <= 0) return false;
  return String(trade?.side || "").toUpperCase() === "SHORT" ? current >= stop : current <= stop;
}

function pnlValueTone(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "text-slate-400";
  return Number(value) >= 0 ? "text-emerald-300" : "text-rose-300";
}

function pnlColor(value) {
  return safeNumber(value, 0) >= 0 ? "#34d399" : "#fb7185";
}

function formatRatio(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "N/A";
}

function isStagedExitPolicy(trade) {
  return STAGED_EXIT_POLICIES.has(String(trade?.exit_policy || "").toUpperCase());
}

function exitDeadline(trade) {
  const openedAt = timestampMillis(trade?.opened_at || trade?.created_at, Number.NaN);
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
