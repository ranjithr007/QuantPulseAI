import clsx from "clsx";
import {
    Activity,
    BarChart3,
    Bot,
    Eye,
    RadioTower,
    ShieldCheck,
    Target,
    TrendingDown,
    TrendingUp,
    Waves,
} from "lucide-react";
import { deriveExecutorState, enrichRow } from "../components/MarketSignalTable";
import Phase2ValidationBadge from "../components/Phase2ValidationBadge";
import AdvancedTradingViewPanel from "../components/signal-details/AdvancedTradingViewPanel";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { deriveSelectedEligibilityState } from "../utils/eligibility";
import { formatDate, formatNumber, formatPercent, formatPrice, formatSigned } from "../utils/formatters";
import { dedupeReasonList } from "../utils/reasonDisplay";
import { humanizeMachineStatus } from "../utils/text";
import { progressToneClass } from "../utils/toneClasses";

const MIN_READY_CONFIDENCE = 65;

export default function DashboardHomePage({
    view,
    auto,
    marketSummary,
    selectedDetail,
    activeTradePlan,
    autoDecision,
    liveStatus,
    watchlist,
    openTrades,
    signalRows,
    candleSeries,
    selectedRisk,
    selectedPaperTradeCandidate,
    onOpenSymbol,
}) {
    const longPct = normalizeProbability(selectedDetail.longSidePct);
    const shortPct = normalizeProbability(selectedDetail.shortSidePct);
    const funding = fundingSnapshot(selectedDetail, activeTradePlan);
    const chartPrice = resolveChartPrice(selectedDetail.currentPrice, view.symbol, signalRows);
    const enrichedRows = signalRows.map((row) => enrichRow(row, watchlist, liveStatus, auto?.minConfidence ?? MIN_READY_CONFIDENCE));
    const topSignals = [...enrichedRows]
        .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))
        .slice(0, 6);
    const eligibleRows = enrichedRows.filter((row) => row.riskLabel === "Eligible" || row.riskLabel === "Ready to execute");
    const blockedRows = enrichedRows.filter((row) => !["Eligible", "Ready to execute"].includes(row.riskLabel));
    const persistedEligible = eligibleRows.filter((row) => row.riskNote?.startsWith("Persisted risk:")).length;
    const computedEligible = eligibleRows.filter((row) => row.riskNote?.startsWith("Computed risk:")).length;
    const fallbackEligible = eligibleRows.filter((row) => row.riskNote?.startsWith("Trigger fallback:")).length;
    const eligibilityState = deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
    const rotation = rotationSignal(enrichedRows, marketSummary);

    return (
        <section className="border-b border-white/5 bg-slate-950/55">
            <div className="mx-auto grid min-w-0 w-full max-w-[1680px] gap-3.5 px-3 py-3 sm:px-6 sm:py-4 lg:px-8">
                <div className="grid min-w-0 items-start gap-3.5 2xl:grid-cols-[minmax(0,1fr)_430px]">
                    <div className="min-w-0 self-start rounded-lg border border-white/10 bg-slate-900/75 p-3 sm:p-3.5">
                        <div className="flex flex-col gap-2.5 lg:flex-row lg:items-start lg:justify-between">
                            <div>
                                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
                                    <Activity className="h-4 w-4 text-cyan-300" />
                                    Dashboard Home
                                </div>
                                <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">
                                    {view.symbol} dashboard
                                </h2>
                                <div className="mt-1 text-xs text-slate-500">
                                    Live feed, AI bias, and risk gate in one view
                                </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <Pill tone={selectedDetail.regimeTone}>{selectedDetail.regimeLabel || "WAIT"}</Pill>
                                <Pill tone={selectedDetail.signalType === "BUY" ? "emerald" : selectedDetail.signalType === "SELL" ? "rose" : "slate"}>
                                    {selectedDetail.signalType}
                                </Pill>
                                <Pill tone={eligibilityState.tone}>
                                    {compactEligibilityLabel(eligibilityState.label)}
                                </Pill>
                            </div>
                        </div>

                        <div className="mt-3.5 grid gap-3">
                            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                                <MetricCard
                                    label="Market regime"
                                    value={selectedDetail.regimeLabel || "WAIT"}
                                    note={selectedDetail.regimeReason || "No regime summary"}
                                    icon={Waves}
                                    accent={selectedDetail.regimeTone || "cyan"}
                                    compact
                                />
                                <MetricCard
                                    label="Crypto rotation"
                                    value={rotation.label}
                                    note={rotation.note}
                                    icon={RadioTower}
                                    accent={rotation.tone}
                                    compact
                                />
                                <MetricCard
                                    label="Long / short bias"
                                    value={`${formatPercent(longPct, 0)} / ${formatPercent(shortPct, 0)}`}
                                    note="Probability engine"
                                    icon={BarChart3}
                                    accent={longPct >= shortPct ? "emerald" : "rose"}
                                    compact
                                />
                            </div>
                                <MetricCard
                                    label="Risk gate"
                                    value={riskGateLabel(auto, selectedRisk, autoDecision, selectedDetail, openTrades)}
                                    note={autoDecision.reason || humanizeMachineStatus(selectedRisk?.status, "Risk engine")}
                                    icon={ShieldCheck}
                                    accent={eligibilityState.tone === "emerald" ? "emerald" : eligibilityState.tone === "amber" ? "amber" : "rose"}
                                compact
                            />
                        </div>

                        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3 2xl:grid-cols-4">
                            <PulseCard
                                label="Live source"
                                value={liveStatus?.running ? "Live feed" : "Cache mode"}
                                note={
                                    liveStatus?.running
                                        ? `${liveStatus?.cached_count ?? 0} cached symbols`
                                        : "Starting live feed"
                                }
                                icon={RadioTower}
                                tone={liveStatus?.running ? "emerald" : "amber"}
                            />
                                <PulseCard
                                    label="AI confidence"
                                    value={formatPercent(selectedDetail.confidence, 0, "-")}
                                    note="Calculated"
                                    icon={Bot}
                                    tone={selectedDetail.confidence >= MIN_READY_CONFIDENCE ? "emerald" : "amber"}
                                />
                            <PulseCard
                                label="Eligible setups"
                                value={eligibleRows.length}
                                note={`P ${persistedEligible} • C ${computedEligible} • T ${fallbackEligible}`}
                                icon={ShieldCheck}
                                tone="cyan"
                            />
                            <PulseCard
                                label="Open trades"
                                value={openTrades.length}
                                note={`Eligible ${eligibleRows.length} • Blocked ${blockedRows.length}`}
                                icon={BarChart3}
                                tone={eligibilityState.tone === "emerald" ? "emerald" : eligibilityState.tone === "amber" ? "amber" : "rose"}
                            />
                            <PulseCard
                                label="Executor ready"
                                value={marketSummary.executorReadyCount ?? 0}
                                note="Queued + clear"
                                icon={ShieldCheck}
                                tone="emerald"
                            />
                            <PulseCard
                                label="Executor blocked"
                                value={marketSummary.executorBlockedCount ?? 0}
                                note="Queued + blocked"
                                icon={Target}
                                tone="rose"
                            />
                            <PulseCard
                                label="No queued plan"
                                value={marketSummary.noQueuedPlanCount ?? 0}
                                note="Not queued yet"
                                icon={BarChart3}
                                tone="amber"
                            />
                            <div className="sm:col-span-2 lg:col-span-3 xl:col-span-3 2xl:col-span-4">
                                <AdvancedTradingViewPanel
                                    currentPrice={chartPrice}
                                    symbol={view.symbol}
                                    timeframe={view.timeframe}
                                    tradePlan={activeTradePlan || selectedDetail.tradePlan}
                                    resistanceLevels={selectedDetail.resistanceLevels}
                                    supportLevels={selectedDetail.supportLevels}
                                />
                            </div>
                            <div className="sm:col-span-2 lg:col-span-3 xl:col-span-3 2xl:col-span-4">
                                <SignalScreener rows={topSignals} activeSymbol={view.symbol} onOpenSymbol={onOpenSymbol} />
                            </div>
                        </div>
                    </div>

                    <div className="grid self-start gap-3 md:grid-cols-1">
                        <BiasPanel longPct={longPct} shortPct={shortPct} selectedDetail={selectedDetail} activeTradePlan={activeTradePlan} />
                        <AutomationPanel autoDecision={autoDecision} selectedRisk={selectedRisk} openTrades={openTrades} selectedDetail={selectedDetail} eligibilityState={eligibilityState} selectedPaperTradeCandidate={selectedPaperTradeCandidate} />
                        <MicrostructurePanel selectedDetail={selectedDetail} funding={funding} />
                    </div>
                </div>
            </div>
        </section>
    );
}

function BiasPanel({ longPct, shortPct, selectedDetail, activeTradePlan }) {
    const dominant = longPct >= shortPct ? "LONG BIAS" : "SHORT BIAS";
    const biasGap = Math.abs(longPct - shortPct);
    const riskReward = activeTradePlan?.risk_reward ?? selectedDetail.tradePlan?.risk_reward;

    return (
        <div className="rounded-lg border border-white/10 bg-slate-900/75 p-3">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <div className="text-sm font-semibold text-white">Directional bias</div>
                    <div className="mt-0.5 line-clamp-2 max-w-[28rem] text-xs leading-4 text-slate-500">
                        {selectedDetail.regimeReason || "Regime context pending"}
                    </div>
                </div>
                <Pill tone={longPct >= shortPct ? "emerald" : "rose"}>{dominant}</Pill>
            </div>

            <div className="mt-3 space-y-2">
                <BiasMeter label="Long" value={longPct} tone="emerald" />
                <BiasMeter label="Short" value={shortPct} tone="rose" />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-3">
                <CompactStat label="Long" value={formatPercent(longPct, 0, "-")} tone="emerald" />
                <CompactStat label="Short" value={formatPercent(shortPct, 0, "-")} tone="rose" />
                <CompactStat label="Gap" value={formatPercent(biasGap, 0, "-")} tone={biasGap >= 25 ? "cyan" : "slate"} />
                <CompactStat label="Confidence" value={formatPercent(selectedDetail.confidence, 0, "-")} tone={selectedDetail.confidence >= MIN_READY_CONFIDENCE ? "emerald" : "amber"} />
                <CompactStat label="RR" value={formatSigned(riskReward, 2, "-")} tone={Number(riskReward || 0) >= 1.5 ? "emerald" : "amber"} />
                <CompactStat label="Regime" value={selectedDetail.regimeLabel || "WAIT"} tone="cyan" />
            </div>
        </div>
    );
}

function AutomationPanel({ autoDecision, selectedRisk, openTrades, selectedDetail, eligibilityState, selectedPaperTradeCandidate }) {
    const blockedReasons = dedupeReasonList(autoDecision.reasons || []).slice(0, 3);
    const warningReasons = dedupeReasonList(autoDecision.warnings || []);
    const executorBlockedReasons = dedupeReasonList(selectedPaperTradeCandidate?.blocked_reasons || []);
    const riskTone = selectedRisk?.is_usable === false ? "rose" : selectedRisk?.decision === "APPROVE" ? "emerald" : "cyan";
    const entryTrigger = selectedDetail?.timing?.trigger || selectedDetail?.entryTrigger?.trigger || selectedDetail?.timing || selectedDetail?.entryTrigger || null;
    const tradeSetup = selectedDetail?.prediction?.setup || selectedDetail?.tradeSetup?.setup || selectedDetail?.prediction || selectedDetail?.tradeSetup || null;
    const executionReason = entryTrigger?.reason || tradeSetup?.reason || selectedRisk?.reason || "No execution reason available";
    const executionWaiting = entryTrigger?.status === "WAIT";
    const executor = deriveExecutorState(
        {
            symbol: selectedDetail?.symbol,
            type: selectedDetail?.signalType,
        },
        selectedPaperTradeCandidate ? [selectedPaperTradeCandidate] : []
    );

    return (
        <div className="rounded-lg border border-white/10 bg-slate-900/75 p-3">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <div className="text-sm font-semibold text-white">Risk and auto-trading</div>
                    <div className="mt-0.5 line-clamp-2 max-w-[34rem] text-xs leading-4 text-slate-500">
                        {autoDecision.reason || humanizeMachineStatus(selectedRisk?.status, "Eligibility, blocks, exposure")}
                    </div>
                </div>
                <div className="flex flex-wrap justify-end gap-2">
                    {autoDecision.stackState ? <Pill tone={autoDecision.stackState === "ALIGNED" ? "emerald" : autoDecision.stackState === "MIXED_STRONG" ? "rose" : "amber"}>{autoDecision.stackState}</Pill> : null}
                    <Pill tone={eligibilityState.tone}>{eligibilityState.label}</Pill>
                </div>
            </div>

            <div className={clsx("mt-3 rounded-lg border px-3 py-2.5", executionWaiting ? "border-amber-400/20 bg-amber-500/10 text-amber-100" : "border-emerald-400/20 bg-emerald-500/10 text-emerald-100")}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium">
                        {executionWaiting ? "Waiting for timing confirmation" : "Execution-ready"}
                    </div>
                    <Pill tone={executionWaiting ? "amber" : "emerald"}>{humanizeMachineStatus(entryTrigger?.status, "Unknown")}</Pill>
                </div>
                <div className="mt-1.5 text-xs leading-5 opacity-90">{executionReason}</div>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 xl:grid-cols-2 2xl:grid-cols-3">
                <StatusTile label="Open trades" value={openTrades.length} icon={Bot} />
                <StatusTile label="Risk decision" value={selectedRisk?.decision || humanizeMachineStatus(selectedRisk?.status, "Wait")} icon={ShieldCheck} tone={riskTone} />
                <StatusTile label="Risk %" value={formatPercent(selectedRisk?.risk_percent, 1, "-")} icon={Target} tone="cyan" />
                <StatusTile label="Position" value={formatNumber(selectedRisk?.position_size, 2, "-")} icon={BarChart3} tone={riskTone} />
                <StatusTile label="Executor" value={executor.label} icon={ShieldCheck} tone={executor.tone} />
            </div>

            <div className="mt-3 grid gap-2 xl:grid-cols-2">
                <CompactDiagnostic
                    label="Eligibility"
                    value={eligibilityState.label}
                    note={autoDecision.reason || "Eligibility summary"}
                    tone={eligibilityState.tone}
                />
                <CompactDiagnostic
                    label="Executor truth"
                    value={executor.label}
                    note={executor.note || "Executor summary unavailable"}
                    tone={executor.tone}
                />
                <CompactDiagnostic
                    label="Top block"
                    value={topReasonLabel(autoDecision.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
                    note={topReasonNote(autoDecision.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
                    tone={topReasonTone(autoDecision.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
                />
                <CompactDiagnostic
                    label="Timing"
                    value={humanizeMachineStatus(entryTrigger?.status, "Unknown")}
                    note={executionReason}
                    tone={timingTone(entryTrigger?.status)}
                />
            </div>

            <div className="mt-3">
                <Phase2ValidationBadge
                    symbol={selectedDetail?.symbol}
                    timeframe={selectedDetail?.timeframe || "1h"}
                    signalType={selectedDetail?.signalType}
                />
            </div>

            <div className="mt-3">
                <LifecyclePanel
                    stages={paperTradeLifecycle({
                        symbol: selectedDetail?.symbol,
                        eligibilityState,
                        selectedPaperTradeCandidate,
                        openTrades,
                    })}
                />
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
                {warningReasons.length ? (
                    warningReasons.map((warning) => (
                        <div key={warning} className="rounded-lg border border-amber-400/20 bg-amber-500/10 px-2.5 py-1.5 text-[11px] font-medium text-amber-200">
                            {warning}
                        </div>
                    ))
                ) : null}
                {(blockedReasons.length ? blockedReasons : ["No blocking reason"]).map((reason) => (
                    <div key={reason} className="rounded-lg border border-white/10 bg-slate-950/65 px-2.5 py-1.5 text-[11px] font-medium text-slate-300">
                        {reason}
                    </div>
                ))}
                {executorBlockedReasons.map((reason) => (
                    <div key={`executor-${reason}`} className="rounded-lg border border-rose-400/20 bg-rose-500/10 px-2.5 py-1.5 text-[11px] font-medium text-rose-200">
                        {reason}
                    </div>
                ))}
            </div>
        </div>
    );
}

function BiasMeter({ label, value, tone }) {
    return (
        <div>
            <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                <span className="font-medium text-slate-300">{label}</span>
                <span className="font-semibold text-white">{formatPercent(value, 0, "-")}</span>
            </div>
            <div className="h-2 rounded-full bg-slate-950">
                <div className={clsx("h-full rounded-full", progressToneClass(tone))} style={{ width: `${Math.max(0, Math.min(value, 100))}%` }} />
            </div>
        </div>
    );
}

function CompactStat({ label, value, tone = "slate" }) {
    const toneClass = {
        emerald: "text-emerald-200",
        rose: "text-rose-200",
        amber: "text-amber-200",
        cyan: "text-cyan-200",
        slate: "text-slate-100",
    }[tone];

    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/65 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
            <div className={clsx("mt-1 truncate text-sm font-semibold", toneClass)}>{value}</div>
        </div>
    );
}

function CompactDiagnostic({ label, value, note, tone = "slate" }) {
    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/65 px-2.5 py-2">
            <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
                <Pill tone={tone}>{value ?? "-"}</Pill>
            </div>
            <div className="mt-1.5 line-clamp-3 text-xs leading-5 text-slate-400" title={note || "-"}>
                {note || "-"}
            </div>
        </div>
    );
}

function LifecyclePanel({ stages = [] }) {
    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/55 p-2.5">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <div className="text-sm font-medium text-white">Paper-trade lifecycle</div>
                    <div className="text-xs text-slate-500">Selected setup progress from gate pass to open trade</div>
                </div>
            </div>
            <div className="mt-3 grid gap-2 xl:grid-cols-2">
                {stages.map((stage) => (
                    <div key={stage.key} className="rounded-lg border border-white/10 bg-slate-950/65 px-2.5 py-2">
                        <div className="flex items-center justify-between gap-2">
                            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{stage.label}</div>
                            <Pill tone={stage.tone}>{stage.state}</Pill>
                        </div>
                        <div className="mt-1.5 line-clamp-3 text-xs leading-5 text-slate-400" title={stage.note}>
                            {stage.note}
                        </div>
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
    if (riskReasons?.length) return `Auto rules report ${riskReasons.length} active block(s)`;
    if (executorReasons?.length) return `Executor reports ${executorReasons.length} active block(s)`;
    return "No active automation or executor blocks";
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

function paperTradeLifecycle({ symbol, eligibilityState, selectedPaperTradeCandidate, openTrades = [] }) {
    const selectedOpenTrade = openTrades.find((trade) => String(trade?.symbol || "").toUpperCase() === String(symbol || "").toUpperCase());
    const eligible = ["Eligible", "Ready to execute"].includes(String(eligibilityState?.label || ""));
    const candidateExists = Boolean(selectedPaperTradeCandidate);
    const executorReady = Boolean(selectedPaperTradeCandidate?.eligible);
    const openNow = Boolean(selectedOpenTrade);
    const queuedAt = selectedPaperTradeCandidate?.trade_plan?.created_at || null;
    const executorCheckedAt = selectedPaperTradeCandidate?.risk_decision?.created_at || queuedAt || null;
    const openedAt = selectedOpenTrade?.opened_at || selectedOpenTrade?.created_at || null;
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
            state: "Track in PnL",
            tone: "slate",
            note: "Closed lifecycle outcomes appear in the PnL and trade history views.",
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

function SignalScreener({ rows, activeSymbol, onOpenSymbol }) {
    return (
        <div className="overflow-hidden rounded-lg border border-white/10 bg-slate-900/75">
            <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
                <div>
                    <div className="text-sm font-semibold text-white">Signal screener</div>
                    <div className="text-xs text-slate-500">Ranked by confidence</div>
                </div>
                <Pill tone="cyan">{rows.length} tracked</Pill>
            </div>
            <div className="overflow-x-auto">
                <table className="min-w-[760px] divide-y divide-white/5 text-left text-sm">
                    <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                        <tr>
                            <th className="px-3 py-2">Symbol</th>
                            <th className="px-3 py-2">Signal</th>
                            <th className="px-3 py-2">Confidence</th>
                            <th className="px-3 py-2">Price</th>
                            <th className="px-3 py-2">Details</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                        {rows.map((row) => (
                            <tr key={row.symbol} className={clsx("transition", activeSymbol === row.symbol && "bg-cyan-500/10")}>
                                <td className="px-3 py-2 font-medium text-white">{row.symbol}</td>
                                <td className="px-3 py-2">
                                    <div className="flex flex-wrap items-center gap-1.5">
                                        <Pill tone={row.type === "BUY" ? "emerald" : row.type === "SELL" ? "rose" : "slate"}>{row.type}</Pill>
                                        <Pill tone={riskSourceTone(row.riskSource)}>{riskSourceLabel(row.riskSource)}</Pill>
                                    </div>
                                </td>
                                <td className="px-3 py-2 text-slate-300">{formatPercent(row.confidence, 0)}</td>
                                <td className="px-3 py-2 text-slate-300">{formatPrice(row.currentPrice, { fallback: "-", compactSmall: true })}</td>
                                <td className="px-3 py-2">
                                    <button
                                        type="button"
                                        onClick={() => onOpenSymbol(row.symbol)}
                                        className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-slate-950/70 px-3 py-1.5 text-xs font-medium text-cyan-200 transition hover:border-cyan-400/40 hover:bg-cyan-500/10"
                                    >
                                        <Eye className="h-3.5 w-3.5" />
                                        View Details
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function MicrostructurePanel({ selectedDetail, funding }) {
    const whaleBuyPct = Math.round((selectedDetail.whaleBuyVolume / selectedDetail.whaleMaxVolume) * 100);
    const whaleSellPct = Math.round((selectedDetail.whaleSellVolume / selectedDetail.whaleMaxVolume) * 100);

    return (
        <div className="rounded-lg border border-white/10 bg-slate-900/75 p-3.5">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <div className="text-sm font-semibold text-white">Orderflow, SMC, funding</div>
                    <div className="text-xs text-slate-500">Microstructure context</div>
                </div>
                <Pill tone={selectedDetail.orderflowTone}>{selectedDetail.orderflowBadge || "FLOW"}</Pill>
            </div>

            <div className="mt-3.5 grid gap-3">
                <FlowLine label="Orderflow delta" value={formatNumber(flowDelta(selectedDetail), 2, "-")} tone={selectedDetail.orderflowTone} icon={Activity} />
                <FlowLine label="SMC bias" value={selectedDetail.smcBadge || "N/A"} tone={selectedDetail.smcTone} icon={Waves} />
                <FlowLine label="Whale buy volume" value={formatNumber(selectedDetail.whaleBuyVolume, 0, "-")} tone="emerald" icon={TrendingUp} progress={whaleBuyPct} />
                <FlowLine label="Whale sell volume" value={formatNumber(selectedDetail.whaleSellVolume, 0, "-")} tone="rose" icon={TrendingDown} progress={whaleSellPct} />
                <FlowLine label="Funding pressure" value={funding.label} tone={funding.tone} icon={Target} />
            </div>
        </div>
    );
}

function FlowLine({ label, value, tone = "slate", icon: Icon, progress }) {
    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/65 p-3">
            <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                    <Icon className="h-4 w-4 text-slate-500" />
                    <span className="truncate text-sm text-slate-300">{label}</span>
                </div>
                <span className="text-sm font-medium text-white">{value}</span>
            </div>
            {typeof progress === "number" ? (
                <div className="mt-3 h-1.5 rounded-full bg-slate-800">
                    <div className={clsx("h-full rounded-full", progressToneClass(tone))} style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }} />
                </div>
            ) : null}
        </div>
    );
}

function StatusTile({ label, value, icon: Icon, tone = "slate" }) {
    const toneClass = {
        emerald: "text-emerald-200",
        rose: "text-rose-200",
        amber: "text-amber-200",
        cyan: "text-cyan-200",
        slate: "text-white",
    }[tone];

    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/65 p-2.5">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                <Icon className="h-3.5 w-3.5" />
                {label}
            </div>
            <div className={clsx("mt-1.5 truncate text-sm font-semibold", toneClass)}>{value}</div>
        </div>
    );
}

function PulseCard({ label, value, note, icon: Icon, tone }) {
    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/55 px-3 py-2.5">
            <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
                    <div className="mt-1 truncate text-sm font-semibold text-white">{value}</div>
                    <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-slate-400" title={note}>
                        {note}
                    </div>
                </div>
                <div className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-lg border", pulseToneClass(tone))}>
                    <Icon className="h-3.5 w-3.5" />
                </div>
            </div>
        </div>
    );
}

function riskSourceLabel(source) {
    const value = String(source || "").toLowerCase();
    if (value === "persisted") return "Persisted";
    if (value === "computed") return "Computed";
    return "Fallback";
}

function riskSourceTone(source) {
    const value = String(source || "").toLowerCase();
    if (value === "persisted") return "cyan";
    if (value === "computed") return "amber";
    return "slate";
}

function compactEligibilityLabel(label) {
    const value = String(label || "");
    if (value === "Ready to execute") return "AUTO READY";
    if (value === "Eligible") return "AUTO ELIGIBLE";
    if (value === "Blocked by confidence") return "CONFIDENCE BLOCK";
    if (value === "Blocked by risk") return "RISK BLOCK";
    if (value === "Auto trading locked") return "AUTO LOCKED";
    if (value === "Emergency stop") return "EMERGENCY STOP";
    return value.toUpperCase() || "AUTO BLOCKED";
}

function pulseToneClass(tone) {
    return {
        emerald: "border-emerald-400/20 bg-emerald-500/10 text-emerald-200",
        rose: "border-rose-400/20 bg-rose-500/10 text-rose-200",
        amber: "border-amber-400/20 bg-amber-500/10 text-amber-200",
        cyan: "border-cyan-400/20 bg-cyan-500/10 text-cyan-200",
    }[tone || "cyan"];
}

function rotationSignal(rows, marketSummary) {
    const ready = rows.filter((row) => row.riskLabel === "Eligible" || row.riskLabel === "Ready to execute").length;
    const long = rows.filter((row) => row.type === "BUY").length || marketSummary?.buyCount || 0;
    const short = rows.filter((row) => row.type === "SELL").length || marketSummary?.sellCount || 0;

    if (ready === 0) return { label: "Defensive", note: "No ready setups", tone: "amber" };
    if (long > short) return { label: "Risk-on", note: `${long} long setups leading`, tone: "emerald" };
    if (short > long) return { label: "Risk-off", note: `${short} short setups leading`, tone: "rose" };
    return { label: "Balanced", note: `${ready} ready setups`, tone: "cyan" };
}

function fundingSnapshot(selectedDetail, activeTradePlan) {
    const derivatives = selectedDetail?.derivatives || {};
    const fundingRate = finiteNumberOrNull(
        derivatives?.latest_funding_rate ??
        derivatives?.latestFundingRate ??
        derivatives?.funding?.latest?.rate ??
        derivatives?.fundingRateGraph?.slice?.(-1)?.[0]?.value
    );
    const openInterestChange = finiteNumberOrNull(
        derivatives?.latest_open_interest_change_pct ??
        derivatives?.latestOpenInterestChangePct ??
        derivatives?.openInterest?.latest_change_pct ??
        derivatives?.openInterestGraph?.slice?.(-1)?.[0]?.change_pct
    );
    const rr = Number(activeTradePlan?.risk_reward ?? selectedDetail.tradePlan?.risk_reward ?? 0);
    const longPct = normalizeProbability(selectedDetail.longSidePct);
    const shortPct = normalizeProbability(selectedDetail.shortSidePct);

    if (Number.isFinite(fundingRate) || Number.isFinite(openInterestChange)) {
        if (fundingRate > 0 && openInterestChange > 0) return { label: "Longs paying, OI rising", tone: "rose" };
        if (fundingRate < 0 && openInterestChange > 0) return { label: "Shorts paying, OI rising", tone: "emerald" };
        if (fundingRate > 0) return { label: "Positive funding", tone: "amber" };
        if (fundingRate < 0) return { label: "Negative funding", tone: "cyan" };
    }

    if (longPct > shortPct + 15 && rr >= 1.5) return { label: "Long supportive", tone: "emerald" };
    if (shortPct > longPct + 15 && rr >= 1.5) return { label: "Short supportive", tone: "rose" };
    if (rr > 0 && rr < 1.2) return { label: "Risk premium weak", tone: "amber" };
    return { label: "Neutral carry", tone: "cyan" };
}

function finiteNumberOrNull(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

function riskGateLabel(auto, selectedRisk, autoDecision, selectedDetail, openTrades) {
    return deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades }).label;
}

function normalizeProbability(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return number <= 1 ? number * 100 : number;
}

function flowDelta(selectedDetail) {
    const record = selectedDetail.selectedOrderflow || {};
    return record.delta ?? record.Delta ?? record.cumulative_delta ?? record.CVD ?? 0;
}

function resolveChartPrice(currentPrice, symbol, signalRows) {
    const direct = Number(currentPrice);
    if (Number.isFinite(direct) && direct > 0) return direct;

    const rowPrice = Number(signalRows.find((row) => row.symbol === symbol)?.currentPrice);
    if (Number.isFinite(rowPrice) && rowPrice > 0) return rowPrice;

    const defaults = {
        BTCUSDT: 66515.99,
        ETHUSDT: 1773.3,
        XRPUSDT: 1.2362,
        SOLUSDT: 74.54,
        BNBUSDT: 613.39,
        DOGEUSDT: 0.1335,
    };

    return defaults[symbol] || 100;
}
