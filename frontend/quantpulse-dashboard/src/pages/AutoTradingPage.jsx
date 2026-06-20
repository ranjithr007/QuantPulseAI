import clsx from "clsx";
import { Bot, Lock, PauseCircle, PlayCircle, ShieldCheck, Unlock, Wallet } from "lucide-react";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { formatPercent } from "../utils/formatters";

const AUTO_DIRECTIONS = ["LONG", "SHORT", "BOTH"];

export default function AutoTradingPage({
  view,
  symbols,
  auto,
  setAuto,
  onEmergencyStop,
  autoDecision,
  selectedDetail,
  openTrades,
}) {
  const state = autoTradingState({ auto, autoDecision, selectedDetail });

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-1.5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Auto Trading</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Automation lock and eligibility</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill tone="cyan">PAPER ONLY</Pill>
            {auto.version ? <Pill tone="slate">POLICY v{auto.version}</Pill> : null}
            <Pill tone={state.tone}>{state.label}</Pill>
            <Pill tone={auto.locked ? "amber" : "emerald"}>{auto.locked ? "LOCKED" : "UNLOCKED"}</Pill>
          </div>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Auto status" value={state.label} note={state.note} icon={state.icon} accent={state.tone} />
          <MetricCard
            label="Selected signal"
            value={selectedDetail.signalType || "WAIT"}
            note={formatPercent(selectedDetail.confidence, 0, "-")}
            icon={Bot}
            accent={selectedDetail.signalType === "BUY" ? "emerald" : selectedDetail.signalType === "SELL" ? "rose" : "slate"}
          />
          <MetricCard
            label="Allowed symbol"
            value={auto.allowedSymbols.includes(view.symbol) ? "Yes" : "No"}
            note={view.symbol}
            icon={ShieldCheck}
            accent={auto.allowedSymbols.includes(view.symbol) ? "emerald" : "rose"}
          />
          <MetricCard label="Open trades" value={openTrades.length} note={`Limit ${auto.maxOpenTrades}`} icon={Wallet} accent={openTrades.length < auto.maxOpenTrades ? "emerald" : "rose"} />
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
            <div className="flex flex-wrap items-center justify-between gap-2.5">
              <div>
                <div className="text-sm font-medium text-white">Lock controls</div>
                <div className="text-xs text-slate-500">Locking prevents eligibility even when risk gates pass</div>
              </div>
              <Pill tone={auto.emergencyStop ? "rose" : auto.locked ? "amber" : "emerald"}>{state.label}</Pill>
            </div>

            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setAuto((current) => ({ ...current, locked: !current.locked, enabled: current.locked ? true : current.enabled }))}
                className={clsx(
                  "inline-flex items-center justify-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition",
                  auto.locked
                    ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20"
                    : "border-amber-400/30 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20"
                )}
              >
                {auto.locked ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
                {auto.locked ? "Unlock auto trading" : "Lock auto trading"}
              </button>
              <button
                type="button"
                onClick={() => onEmergencyStop(!auto.emergencyStop)}
                className={clsx(
                  "inline-flex items-center justify-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition",
                  auto.emergencyStop
                    ? "border-cyan-400/30 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20"
                    : "border-rose-400/30 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20"
                )}
              >
                {auto.emergencyStop ? <PlayCircle className="h-4 w-4" /> : <PauseCircle className="h-4 w-4" />}
                {auto.emergencyStop ? "Clear emergency stop" : "Emergency stop"}
              </button>
            </div>

            <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/70 p-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Automation reason</div>
              <div className="mt-1.5 line-clamp-2 text-sm leading-5 text-slate-200">{state.note}</div>
            </div>
          </div>

          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
            <div className="flex flex-wrap items-center justify-between gap-2.5">
              <div>
                <div className="text-sm font-medium text-white">Eligibility controls</div>
                <div className="text-xs text-slate-500">Allowlist and direction gates</div>
              </div>
              <Pill tone={autoDecision.allowed ? "emerald" : "rose"}>{autoDecision.allowed ? "Eligible" : "Blocked"}</Pill>
            </div>

            <div className="mt-3 grid gap-2.5 lg:grid-cols-2">
              <ControlBlock label="Allowed symbols" value={auto.allowedSymbols.join(", ") || "None"}>
                <div className="flex flex-wrap gap-2">
                  {symbols.map((symbol) => (
                    <button
                      key={symbol}
                      type="button"
                      onClick={() =>
                        setAuto((current) => ({
                          ...current,
                          allowedSymbols: current.allowedSymbols.includes(symbol)
                            ? current.allowedSymbols.filter((item) => item !== symbol)
                            : [...current.allowedSymbols, symbol],
                        }))
                      }
                      className={clsx(
                        "rounded-lg border px-2.5 py-1.5 text-xs transition",
                        auto.allowedSymbols.includes(symbol)
                          ? "border-cyan-400/40 bg-cyan-500/15 text-cyan-200"
                          : "border-white/10 bg-slate-950/70 text-slate-400 hover:border-white/20"
                      )}
                    >
                      {symbol}
                    </button>
                  ))}
                </div>
              </ControlBlock>

              <ControlBlock label="Allowed direction" value={auto.direction}>
                <div className="flex flex-wrap gap-2">
                  {AUTO_DIRECTIONS.map((direction) => (
                    <button
                      key={direction}
                      type="button"
                      onClick={() => setAuto((current) => ({ ...current, direction }))}
                      className={clsx(
                        "rounded-lg border px-2.5 py-1.5 text-xs transition",
                        auto.direction === direction
                          ? "border-cyan-400/40 bg-cyan-500/15 text-cyan-200"
                          : "border-white/10 bg-slate-950/70 text-slate-400 hover:border-white/20"
                      )}
                    >
                      {direction}
                    </button>
                  ))}
                </div>
              </ControlBlock>
            </div>

            <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/70 p-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Blocking reasons</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {autoDecision.reasons.length ? (
                  autoDecision.reasons.map((reason) => <Pill key={reason} tone="rose">{reason}</Pill>)
                ) : (
                  <Pill tone="emerald">No rule violations</Pill>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ControlBlock({ label, value, children }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 p-2">
      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-1.5 text-sm font-medium text-white">{value}</div>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function autoTradingState({ auto, autoDecision, selectedDetail }) {
  if (auto.emergencyStop) return { label: "Emergency stop", note: "Automatic execution is halted until emergency stop is cleared.", tone: "rose", icon: PauseCircle };
  if (auto.locked) return { label: "Auto trading locked", note: "Unlock auto trading before any signal can become eligible.", tone: "amber", icon: Lock };
  if (selectedDetail.confidence < auto.minConfidence) return { label: "Blocked by confidence", note: `Confidence must be at least ${auto.minConfidence}%.`, tone: "amber", icon: ShieldCheck };
  if (autoDecision.reasons?.some((reason) => String(reason).toLowerCase().includes("risk"))) {
    return { label: "Blocked by risk", note: autoDecision.reason, tone: "rose", icon: ShieldCheck };
  }
  if (autoDecision.allowed) return { label: "Eligible", note: "Selected signal passes automation checks.", tone: "emerald", icon: Unlock };
  return { label: "Blocked", note: autoDecision.reason, tone: "rose", icon: Bot };
}
