import clsx from "clsx";
import { AlertTriangle, Gauge, PauseCircle, ShieldAlert, ShieldCheck, SlidersHorizontal, Target } from "lucide-react";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { formatCurrency, formatNumber, formatPercent, safeNumber } from "../utils/formatters";

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
  const state = riskControlState({ auto, autoDecision, selectedDetail, selectedRisk });

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
            value={selectedRisk?.decision || selectedRisk?.status || "Pending"}
            note={selectedRisk?.is_usable === false ? "Risk engine blocked" : "Risk engine"}
            icon={ShieldCheck}
            accent={selectedRisk?.is_usable === false ? "rose" : "cyan"}
          />
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
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

          <div className="grid gap-3">
            <RiskDecisionPanel autoDecision={autoDecision} selectedRisk={selectedRisk} selectedDetail={selectedDetail} symbol={view.symbol} />
          </div>
        </div>
      </div>
    </section>
  );
}

function RiskDecisionPanel({ autoDecision, selectedRisk, selectedDetail, symbol }) {
  const blocks = autoDecision.reasons?.length ? autoDecision.reasons : ["No active risk blocks"];
  const validationErrors = selectedRisk?.validation_errors || [];
  const ignoredReasons = selectedRisk?.ignored_reasons || [];

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Risk decision</div>
          <div className="text-xs text-slate-500">{symbol} selected signal</div>
        </div>
        <Pill tone={autoDecision.allowed ? "emerald" : "rose"}>{autoDecision.allowed ? "Eligible" : "Blocked"}</Pill>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2">
        <StatusBox label="Signal" value={selectedDetail.signalType || "WAIT"} />
        <StatusBox label="Confidence" value={formatPercent(selectedDetail.confidence, 0, "-")} />
        <StatusBox label="Risk %" value={formatPercent(selectedRisk?.risk_percent, 1, "-")} />
        <StatusBox label="Position" value={formatNumber(selectedRisk?.position_size, 2, "-")} />
      </div>

      <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/70 p-2">
        <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Block reasons</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {blocks.map((reason) => (
            <Pill key={reason} tone={reason === "No active risk blocks" ? "emerald" : "rose"}>
              {reason}
            </Pill>
          ))}
          {validationErrors.map((reason) => (
            <Pill key={reason} tone="rose">{reason}</Pill>
          ))}
          {ignoredReasons.map((reason) => (
            <Pill key={reason} tone="amber">{reason}</Pill>
          ))}
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

function riskControlState({ auto, autoDecision, selectedDetail, selectedRisk }) {
  if (auto.emergencyStop) return { label: "Emergency stop", note: "Automation is halted", tone: "rose", icon: AlertTriangle };
  if (auto.locked) return { label: "Auto trading locked", note: "Unlock required before eligibility", tone: "amber", icon: ShieldAlert };
  if (selectedRisk?.is_usable === false) return { label: "Blocked by risk", note: selectedRisk?.decision || "Risk decision rejected", tone: "rose", icon: ShieldAlert };
  if (selectedDetail.confidence < auto.minConfidence) return { label: "Blocked by confidence", note: `Needs ${auto.minConfidence}% minimum`, tone: "amber", icon: Gauge };
  if (autoDecision.allowed) return { label: "Eligible", note: "Risk gates pass", tone: "emerald", icon: ShieldCheck };
  return { label: "Blocked", note: autoDecision.reasons?.[0] || "Rule check failed", tone: "rose", icon: SlidersHorizontal };
}
