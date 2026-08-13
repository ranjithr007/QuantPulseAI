import clsx from "clsx";
import { BarChart3, PauseCircle, ShieldCheck, TrendingUp, Wallet } from "lucide-react";
import MetricCard from "./ui/MetricCard";
import Pill from "./ui/Pill";
import { deriveSelectedEligibilityState } from "../utils/eligibility";
import { formatCurrency, formatPercent, safeNumber } from "../utils/formatters";
import { dedupeReasonList } from "../utils/reasonDisplay";
import { humanizeMachineStatus } from "../utils/text";

const AUTO_DIRECTIONS = ["LONG", "SHORT", "BOTH"];

export default function AutomationSection({
  view,
  symbols,
  auto,
  setAuto,
  onEmergencyStop,
  autoDecision,
  selectedDetail,
  openTrades,
  selectedRisk,
}) {
  const eligibilityState = deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
  const warningPills = dedupeReasonList(autoDecision.warnings || []);
  const reasonPills = dedupeReasonList(autoDecision.reasons || []);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-1.5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Automatic Trading Panel</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Risk-guarded automation</h2>
          </div>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
            <div className="flex flex-wrap items-center justify-between gap-2.5">
              <div>
                <div className="text-sm font-medium text-white">Execution guardrails</div>
                <div className="text-xs text-slate-500">Allowlist, sizing, leverage, and direction controls</div>
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
              <RiskField
                label="Select symbols allowed"
                value={auto.allowedSymbols}
                render={() => (
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
                          "rounded-full border px-3 py-1.5 text-sm transition",
                          auto.allowedSymbols.includes(symbol)
                            ? "border-cyan-400/40 bg-cyan-500/15 text-cyan-200"
                            : "border-white/10 bg-slate-950/70 text-slate-400 hover:border-white/20"
                        )}
                      >
                        {symbol}
                      </button>
                    ))}
                  </div>
                )}
              />

              <RiskField
                label="Allowed trade direction"
                value={auto.direction}
                render={() => (
                  <SegmentedControl
                    value={auto.direction}
                    options={AUTO_DIRECTIONS}
                    onChange={(direction) => setAuto((current) => ({ ...current, direction }))}
                  />
                )}
              />

              <RiskField
                label="Minimum confidence"
                value={`${auto.minConfidence}%`}
                render={() => (
                  <div className="text-xs text-slate-500">Governed execution boundary (full size at 60%)</div>
                )}
              />

              <RiskField
                label="Max risk per trade"
                value={`${auto.maxRiskPerTrade}%`}
                render={() => (
                  <RangeInput
                    value={auto.maxRiskPerTrade}
                    min={0.1}
                    max={5}
                    step={0.1}
                    onChange={(value) => setAuto((current) => ({ ...current, maxRiskPerTrade: value }))}
                  />
                )}
              />

              <RiskField
                label="Daily loss limit"
                value={`${auto.dailyLossLimit}%`}
                render={() => (
                  <RangeInput
                    value={auto.dailyLossLimit}
                    min={0.5}
                    max={15}
                    step={0.5}
                    onChange={(value) => setAuto((current) => ({ ...current, dailyLossLimit: value }))}
                  />
                )}
              />

              <RiskField
                label="Max open trades"
                value={auto.maxOpenTrades}
                render={() => (
                  <NumberInput
                    value={auto.maxOpenTrades}
                    min={1}
                    max={20}
                    step={1}
                    onChange={(value) => setAuto((current) => ({ ...current, maxOpenTrades: value }))}
                  />
                )}
              />

              <RiskField
                label="Max leverage"
                value={`${auto.maxLeverage}x`}
                render={() => (
                  <NumberInput
                    value={auto.maxLeverage}
                    min={1}
                    max={25}
                    step={1}
                    onChange={(value) => setAuto((current) => ({ ...current, maxLeverage: value }))}
                  />
                )}
              />

              <RiskField
                label="Max position size"
                value={formatCurrency(auto.maxPositionSize, 0)}
                render={() => (
                  <NumberInput
                    value={auto.maxPositionSize}
                    min={100}
                    max={1000000}
                    step={100}
                    onChange={(value) => setAuto((current) => ({ ...current, maxPositionSize: value }))}
                  />
                )}
              />
            </div>
          </div>

          <div className="space-y-3">
            <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-white">Automation verdict</div>
                  <div className="text-xs text-slate-500">Risk checks are evaluated against the selected signal</div>
                </div>
                <Pill tone={eligibilityState.tone}>
                  {eligibilityState.label}
                </Pill>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2.5">
                <MetricCard
                  label="Allowed contract"
                  value={auto.allowedSymbols.includes(view.symbol) ? "Yes" : "No"}
                  note={view.symbol}
                  icon={ShieldCheck}
                  accent={auto.allowedSymbols.includes(view.symbol) ? "emerald" : "rose"}
                  compact
                />
                <MetricCard
                  label="Signal confidence"
                  value={formatPercent(autoDecision.confidence ?? selectedDetail.confidence)}
                  note={`${autoDecision.stackState || "STACK"} • Min ${auto.minConfidence}%`}
                  icon={BarChart3}
                  accent={(autoDecision.stackState === "MIXED_STRONG" || (autoDecision.confidence ?? selectedDetail.confidence) < auto.minConfidence) ? "amber" : "emerald"}
                  compact
                />
                <MetricCard
                  label="Open trades"
                  value={openTrades.length}
                  note={`Limit ${auto.maxOpenTrades}`}
                  icon={Wallet}
                  accent={openTrades.length < auto.maxOpenTrades ? "emerald" : "rose"}
                  compact
                />
                <MetricCard
                  label="Direction"
                  value={auto.direction}
                  note={selectedDetail.signalType}
                  icon={TrendingUp}
                  accent="cyan"
                  compact
                />
              </div>

              <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/70 p-2">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Action reason</div>
                <div className="mt-1.5 line-clamp-2 text-sm leading-5 text-slate-200">{humanizeMachineStatus(autoDecision.reason, "No action reason")}</div>
              </div>

              <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/70 p-2">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Risk blocks</div>
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {warningPills.length ? (
                    warningPills.map((warning) => (
                      <Pill key={warning} tone="amber">
                        {warning}
                      </Pill>
                    ))
                  ) : null}
                  {reasonPills.length ? (
                    reasonPills.map((reason) => (
                      <Pill key={reason} tone="rose">
                        {reason}
                      </Pill>
                    ))
                  ) : (
                    <Pill tone="emerald">No rule violations</Pill>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function RiskField({ label, value, render }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 p-3">
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-1.5 line-clamp-1 text-sm font-medium text-white">{Array.isArray(value) ? value.join(", ") : value}</div>
      <div className="mt-2.5">{render()}</div>
    </div>
  );
}

function RangeInput({ value, min, max, step, onChange }) {
  return (
    <div className="space-y-3">
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
      className="w-full rounded-lg border border-white/10 bg-slate-950/80 px-3 py-2 text-sm text-white outline-none transition focus:border-cyan-400/40"
    />
  );
}

function SegmentedControl({ value, options, onChange }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          className={clsx(
            "rounded-full border px-3 py-1.5 text-sm transition",
            value === option
              ? "border-cyan-400/45 bg-cyan-500/15 text-cyan-200"
              : "border-white/10 bg-slate-950/70 text-slate-400 hover:border-white/20 hover:bg-slate-900"
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
