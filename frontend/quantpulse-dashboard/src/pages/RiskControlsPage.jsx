import clsx from "clsx";
import { AlertTriangle, Gauge, PauseCircle, ShieldAlert, ShieldCheck, SlidersHorizontal, Target } from "lucide-react";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { deriveSelectedEligibilityState } from "../utils/eligibility";
import { formatCurrency, formatDate, formatNumber, formatPercent, safeNumber } from "../utils/formatters";
import { buildRiskBlockPills, dedupeReasonList } from "../utils/reasonDisplay";
import { humanizeMachineStatus } from "../utils/text";

export default function RiskControlsPage({
  view,
  auto,
  setAuto,
  onEmergencyStop,
  autoDecision,
  selectedDetail,
  selectedRisk,
  selectedPaperTradeCandidate,
  openTrades,
}) {
  const state = riskControlState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
  const executor = executorRiskState(selectedPaperTradeCandidate);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-1.5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Risk Controls</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Risk gate and execution limits</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill tone="cyan">PAPER POLICY</Pill>
            <Pill tone={state.tone}>{state.label}</Pill>
            <Pill tone={auto.locked ? "amber" : "emerald"}>{auto.locked ? "LOCKED" : "UNLOCKED"}</Pill>
          </div>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Risk state" value={state.label} note={state.note} icon={state.icon} accent={state.tone} />
          <MetricCard
            label="Confidence gate"
            value={formatPercent(selectedDetail.confidence, 0, "-")}
            note={`Minimum ${auto.minConfidence}%`}
            icon={Gauge}
            accent={selectedDetail.confidence >= auto.minConfidence ? "emerald" : "amber"}
          />
          <MetricCard
            label="Open trades"
            value={openTrades.length}
            note={`Limit ${auto.maxOpenTrades}`}
            icon={Target}
            accent={openTrades.length < auto.maxOpenTrades ? "emerald" : "rose"}
          />
          <MetricCard
            label="Backend decision"
            value={selectedRisk?.decision || humanizeMachineStatus(selectedRisk?.status, "Pending")}
            note={selectedRisk?.is_usable === false ? "Risk engine blocked" : "Risk engine"}
            icon={ShieldCheck}
            accent={selectedRisk?.is_usable === false ? "rose" : "cyan"}
          />
          <MetricCard
            label="Executor verdict"
            value={executor.label}
            note={executor.note}
            icon={executor.icon}
            accent={executor.tone}
          />
        </div>

        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-2">
          <DiagnosticStrip
            label="Backend risk"
            value={selectedRisk?.decision || humanizeMachineStatus(selectedRisk?.status, "Pending")}
            note={selectedRisk?.reason || humanizeMachineStatus(selectedRisk?.status, selectedRisk?.is_usable === false ? "Risk engine blocked this plan" : "Risk engine decision is usable")}
            tone={selectedRisk?.is_usable === false ? "rose" : "cyan"}
          />
          <DiagnosticStrip
            label="Executor truth"
            value={executor.label}
            note={executor.note}
            tone={executor.tone}
          />
          <DiagnosticStrip
            label="Top block"
            value={topReasonLabel(autoDecision.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
            note={topReasonNote(autoDecision.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
            tone={topReasonTone(autoDecision.reasons, selectedPaperTradeCandidate?.blocked_reasons)}
          />
          <DiagnosticStrip
            label="Timing stack"
            value={humanizeMachineStatus(selectedDetail.timing?.trigger?.status || selectedDetail.entryTrigger?.trigger?.status || selectedDetail.entryTrigger?.status, "Unknown")}
            note={selectedDetail.timing?.trigger?.reason || selectedDetail.entryTrigger?.trigger?.reason || "No timing explanation available"}
            tone={timingTone(selectedDetail.timing?.trigger?.status || selectedDetail.entryTrigger?.trigger?.status || selectedDetail.entryTrigger?.status)}
          />
        </div>

        <div className="mt-3">
          <LifecyclePanel
            stages={paperTradeLifecycle({
              symbol: view.symbol,
              eligibilityState: state,
              selectedPaperTradeCandidate,
              openTrades,
            })}
          />
        </div>

        <div className="mt-3 grid items-start gap-3 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="self-start rounded-lg border border-white/10 bg-slate-900/70 p-2">
            <div className="flex flex-wrap items-center justify-between gap-2.5">
              <div>
                <div className="text-sm font-medium text-white">Risk limits</div>
                <div className="text-xs text-slate-500">Sizing, confidence, exposure, leverage, and drawdown controls</div>
              </div>
              <button
                type="button"
                onClick={() => onEmergencyStop(true)}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-400/30 bg-rose-500/10 px-3.5 py-2 text-sm font-medium text-rose-200 transition hover:bg-rose-500/20"
              >
                <PauseCircle className="h-4 w-4" />
                Emergency stop
              </button>
            </div>

            <div className="mt-3 grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
              <RiskField label="Minimum confidence" value={`${auto.minConfidence}%`}>
                <RangeInput value={auto.minConfidence} min={0} max={100} step={1} onChange={(minConfidence) => setAuto((current) => ({ ...current, minConfidence }))} />
              </RiskField>
              <RiskField label="Max risk per trade" value={`${auto.maxRiskPerTrade}%`}>
                <RangeInput value={auto.maxRiskPerTrade} min={0.1} max={5} step={0.1} onChange={(maxRiskPerTrade) => setAuto((current) => ({ ...current, maxRiskPerTrade }))} />
              </RiskField>
              <RiskField label="Daily loss limit" value={`${auto.dailyLossLimit}%`}>
                <RangeInput value={auto.dailyLossLimit} min={0.5} max={15} step={0.5} onChange={(dailyLossLimit) => setAuto((current) => ({ ...current, dailyLossLimit }))} />
              </RiskField>
              <RiskField label="Max open trades" value={auto.maxOpenTrades}>
                <NumberInput value={auto.maxOpenTrades} min={1} max={20} step={1} onChange={(maxOpenTrades) => setAuto((current) => ({ ...current, maxOpenTrades }))} />
              </RiskField>
              <RiskField label="Max leverage" value={`${auto.maxLeverage}x`}>
                <NumberInput value={auto.maxLeverage} min={1} max={25} step={1} onChange={(maxLeverage) => setAuto((current) => ({ ...current, maxLeverage }))} />
              </RiskField>
              <RiskField label="Max position size" value={formatCurrency(auto.maxPositionSize, 0)}>
                <NumberInput value={auto.maxPositionSize} min={100} max={1000000} step={100} onChange={(maxPositionSize) => setAuto((current) => ({ ...current, maxPositionSize }))} />
              </RiskField>
            </div>
          </div>

          <div className="grid self-start gap-3">
            <RiskDecisionPanel auto={auto} autoDecision={autoDecision} selectedRisk={selectedRisk} selectedDetail={selectedDetail} symbol={view.symbol} openTrades={openTrades} selectedPaperTradeCandidate={selectedPaperTradeCandidate} />
          </div>
        </div>
      </div>
    </section>
  );
}

function RiskDecisionPanel({ auto, autoDecision, selectedRisk, selectedDetail, symbol, openTrades, selectedPaperTradeCandidate }) {
  const state = deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
  const executor = executorRiskState(selectedPaperTradeCandidate);
  const validationErrors = selectedRisk?.validation_errors || [];
  const ignoredReasons = selectedRisk?.ignored_reasons || [];
  const blockPills = buildRiskBlockPills({
    autoReasons: autoDecision.reasons,
    validationErrors,
    ignoredReasons,
  });
  const executorBlockedReasons = dedupeReasonList(selectedPaperTradeCandidate?.blocked_reasons || []);
  const entryBand = selectedDetail.timing?.trigger?.confidence_window || selectedDetail.entryTrigger?.trigger?.confidence_window || selectedDetail.prediction?.setup?.confidence_window || selectedDetail.tradeSetup?.setup?.confidence_window || null;
  const stackConfidence = selectedDetail.timing?.trigger?.stack_confidence ?? selectedDetail.entryTrigger?.trigger?.stack_confidence ?? selectedDetail.multiTimeframe?.confirmation?.stack_confidence ?? null;
  const predictionStack = selectedDetail.predictionStack?.length ? selectedDetail.predictionStack.join(" / ") : selectedDetail.predictionContext?.prediction_stack?.join(" / ") || selectedDetail.multiTimeframe?.prediction_stack?.join(" / ") || "1h / 2h / 4h / 1d";
  const timingStack = selectedDetail.timingStack?.length
    ? selectedDetail.timingStack.join(" / ")
    : selectedDetail.timing?.trigger?.timing_stack?.join(" / ")
      || selectedDetail.entryTrigger?.trigger?.timing_stack?.join(" / ")
      || selectedDetail.multiTimeframe?.timing_stack?.join(" / ")
      || selectedDetail.multiTimeframe?.entry_stack?.join(" / ")
      || "No lower-timeframe timing layer";

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Risk decision</div>
          <div className="text-xs text-slate-500">{symbol} selected signal</div>
        </div>
        <Pill tone={state.tone}>{state.label}</Pill>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2">
        <StatusBox label="Signal" value={selectedDetail.signalType || "WAIT"} />
        <StatusBox label="Confidence" value={formatPercent(selectedDetail.confidence, 0, "-")} />
        <StatusBox label="Risk %" value={formatPercent(selectedRisk?.risk_percent, 1, "-")} />
        <StatusBox label="Position" value={formatNumber(selectedRisk?.position_size, 2, "-")} />
      </div>

      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <StatusBox label="Prediction" value={humanizeMachineStatus(selectedDetail.prediction?.setup?.status || selectedDetail.tradeSetup?.setup?.status, "Unknown")} />
        <StatusBox label="Timing" value={humanizeMachineStatus(selectedDetail.timing?.trigger?.status || selectedDetail.entryTrigger?.trigger?.status || selectedDetail.entryTrigger?.status, "Unknown")} />
      </div>

      {entryBand ? (
        <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/70 p-2">
          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Entry band</div>
          <div className="mt-1.5 text-sm font-medium text-white">
            {entryBand.min}% - {entryBand.max}% confidence
          </div>
          <div className="mt-1 text-xs text-slate-400">Preferred sweet spot {entryBand.preferred}%</div>
          {stackConfidence !== null && stackConfidence !== undefined ? (
            <div className="mt-1 text-xs text-slate-400">Stack confidence {Number(stackConfidence).toFixed(2)}%</div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <StatusBox label="Prediction stack" value={predictionStack} />
        <StatusBox label="Timing stack" value={timingStack} />
      </div>

      <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/70 p-2">
        <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Execution readiness</div>
        <div className="mt-1.5 text-sm leading-5 text-slate-200">
          {selectedDetail.timing?.trigger?.reason || selectedDetail.entryTrigger?.trigger?.reason || selectedDetail.prediction?.setup?.reason || selectedDetail.tradeSetup?.setup?.reason || "No execution reason available"}
        </div>
      </div>

      <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/70 p-2">
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Executor truth</div>
          <Pill tone={executor.tone}>{executor.label}</Pill>
        </div>
        <div className="mt-1.5 text-sm leading-5 text-slate-200">{executor.note}</div>
        {executorBlockedReasons.length ? (
          <div className="mt-2 flex flex-wrap gap-2">
            {executorBlockedReasons.map((reason) => (
              <Pill key={reason} tone="rose">{reason}</Pill>
            ))}
          </div>
        ) : selectedPaperTradeCandidate ? (
          <div className="mt-2 flex flex-wrap gap-2">
            <Pill tone="emerald">No executor blocks</Pill>
            <Pill tone="cyan">{selectedPaperTradeCandidate.side}</Pill>
          </div>
        ) : null}
      </div>

      <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/70 p-2">
        <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Block reasons</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {blockPills.length ? blockPills.map(({ reason, tone }) => (
            <Pill key={`${tone}:${reason}`} tone={tone}>{reason}</Pill>
          )) : (
            <Pill tone="emerald">No active risk blocks</Pill>
          )}
        </div>
      </div>
    </div>
  );
}

function RiskField({ label, value, children }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 p-2">
      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-2 text-sm font-medium text-white">{value}</div>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function StatusBox({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 p-2">
      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1.5 truncate text-sm font-medium text-white">{value}</div>
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
          <div className="text-xs text-slate-500">Where the selected setup sits in the execution pipeline</div>
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

function RangeInput({ value, min, max, step, onChange }) {
  return (
    <div className="space-y-2.5">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(safeNumber(event.target.value, value))}
        className="w-full accent-cyan-400"
      />
      <div className="flex items-center justify-between text-[11px] text-slate-500">
        <span>{min}</span>
        <span>{value}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}

function NumberInput({ value, min, max, step, onChange }) {
  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(event) => onChange(safeNumber(event.target.value, value))}
      className="w-full rounded-lg border border-white/10 bg-slate-950/80 px-3 py-1.5 text-sm text-white outline-none transition focus:border-cyan-400/40"
    />
  );
}

function riskControlState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades }) {
  const state = deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });

  if (state.label === "Emergency stop") return { ...state, note: "Automation is halted", icon: AlertTriangle };
  if (state.label === "Auto trading locked") return { ...state, note: "Unlock required before eligibility", icon: ShieldAlert };
  if (state.label === "Blocked by risk") return { ...state, icon: ShieldAlert };
  if (state.label === "Blocked by confidence") return { ...state, note: `Needs ${auto.minConfidence}% minimum`, icon: Gauge };
  if (state.label === "Eligible" || state.label === "Ready to execute") return { ...state, note: "Risk gates pass", icon: ShieldCheck };
  return { ...state, icon: SlidersHorizontal };
}

function executorRiskState(candidate) {
  if (!candidate) {
    return {
      label: "No queued plan",
      note: "No OPEN trade plan is currently queued for the executor on this symbol.",
      tone: "amber",
      icon: AlertTriangle,
    };
  }

  if (candidate.eligible) {
    return {
      label: "Executor ready",
      note: "Queued OPEN trade plan matches current backend checks.",
      tone: "emerald",
      icon: ShieldCheck,
    };
  }

  return {
    label: "Executor blocked",
    note: candidate.blocked_reasons?.[0] || "Queued OPEN trade plan is blocked.",
    tone: "rose",
    icon: ShieldAlert,
  };
}

function topReasonLabel(riskReasons = [], executorReasons = []) {
  const reason = (riskReasons && riskReasons[0]) || (executorReasons && executorReasons[0]);
  return reason || "No active blocks";
}

function topReasonNote(riskReasons = [], executorReasons = []) {
  if (riskReasons?.length) return `Risk gate reports ${riskReasons.length} active block(s)`;
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
