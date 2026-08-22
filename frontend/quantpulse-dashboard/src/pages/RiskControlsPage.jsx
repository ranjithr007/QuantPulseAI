import clsx from "clsx";
import { AlertTriangle, Gauge, PauseCircle, ShieldAlert, ShieldCheck, SlidersHorizontal, Target } from "lucide-react";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { deriveSelectedEligibilityState } from "../utils/eligibility";
import { formatInr, formatNumber, formatPercent, safeNumber } from "../utils/formatters";
import { buildRiskBlockPills } from "../utils/reasonDisplay";
import { humanizeMachineStatus } from "../utils/text";

export default function RiskControlsPage({
  view,
  auto,
  setAuto,
  onEmergencyStop,
  autoDecision,
  selectedDetail,
  selectedRisk,
  openTrades,
}) {
  const state = riskControlState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
  const riskReasons = autoDecision.reasons || [];

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
        </div>

        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-2">
          <DiagnosticStrip
            label="Backend risk"
            value={selectedRisk?.decision || humanizeMachineStatus(selectedRisk?.status, "Pending")}
            note={selectedRisk?.reason || humanizeMachineStatus(selectedRisk?.status, selectedRisk?.is_usable === false ? "Risk engine blocked this plan" : "Risk engine decision is usable")}
            tone={selectedRisk?.is_usable === false ? "rose" : "cyan"}
          />
          <DiagnosticStrip
            label="Top risk block"
            value={riskReasons[0] || "No active risk blocks"}
            note={riskReasons.length ? `Risk gate reports ${riskReasons.length} active block(s)` : "Current risk rules report no active blocks"}
            tone={riskReasons.length ? "rose" : "emerald"}
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
                <div className="text-xs text-slate-500">Governed execution boundary (full size at 60%)</div>
              </RiskField>
              <RiskField label="Max risk per trade" value={`${auto.maxRiskPerTrade}%`}>
                <RangeInput value={auto.maxRiskPerTrade} min={0.1} max={5} step={0.1} onChange={(maxRiskPerTrade) => setAuto((current) => ({ ...current, maxRiskPerTrade }))} />
              </RiskField>
              <RiskField label="Daily loss limit" value={`${auto.dailyLossLimit}%`}>
                <RangeInput value={auto.dailyLossLimit} min={0.5} max={4} step={0.5} onChange={(dailyLossLimit) => setAuto((current) => ({ ...current, dailyLossLimit }))} />
              </RiskField>
              <RiskField label="Max open trades" value={auto.maxOpenTrades}>
                <NumberInput value={auto.maxOpenTrades} min={1} max={4} step={1} onChange={(maxOpenTrades) => setAuto((current) => ({ ...current, maxOpenTrades }))} />
              </RiskField>
              <RiskField label="Max leverage" value={`${auto.maxLeverage}x`}>
                <NumberInput value={auto.maxLeverage} min={1} max={25} step={1} onChange={(maxLeverage) => setAuto((current) => ({ ...current, maxLeverage }))} />
              </RiskField>
              <RiskField label="INR-M paper capital" value={formatInr(auto.paperCapitalInr || 100000)}>
                <div className="text-xs text-slate-500">75% minimum tier / 85% maximum tier; {formatInr(auto.maxPositionSize || 85000)} maximum notional</div>
              </RiskField>
            </div>
          </div>

          <div className="grid self-start gap-3">
            <RiskDecisionPanel auto={auto} autoDecision={autoDecision} selectedRisk={selectedRisk} selectedDetail={selectedDetail} symbol={view.symbol} openTrades={openTrades} />
          </div>
        </div>
      </div>
    </section>
  );
}
function RiskDecisionPanel({ auto, autoDecision, selectedRisk, selectedDetail, symbol, openTrades }) {
  const state = deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
  const validationErrors = selectedRisk?.validation_errors || [];
  const ignoredReasons = selectedRisk?.ignored_reasons || [];
  const blockPills = buildRiskBlockPills({
    autoReasons: autoDecision.reasons,
    validationErrors,
    ignoredReasons,
  });

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Risk decision</div>
          <div className="text-xs text-slate-500">{symbol} selected signal</div>
        </div>
        <Pill tone={state.tone}>{state.label}</Pill>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <StatusBox label="Signal" value={selectedDetail.signalType || "WAIT"} />
        <StatusBox label="Confidence" value={formatPercent(selectedDetail.confidence, 0, "-")} />
        <StatusBox label="Size tier" value={humanizeMachineStatus(selectedRisk?.position_tier, "-")} />
        <StatusBox label="Risk %" value={formatPercent(selectedRisk?.risk_percent, 1, "-")} />
        <StatusBox label="Position" value={formatNumber(selectedRisk?.position_size, 2, "-")} />
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
