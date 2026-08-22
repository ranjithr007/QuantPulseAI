import clsx from "clsx";
import { Bot, Lock, PauseCircle, PlayCircle, ShieldCheck, Unlock, Wallet } from "lucide-react";
import Phase2ValidationBadge from "../components/Phase2ValidationBadge";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { deriveSelectedEligibilityState } from "../utils/eligibility";
import { formatDate, formatPercent } from "../utils/formatters";
import { dedupeReasonList } from "../utils/reasonDisplay";
import { humanizeMachineStatus } from "../utils/text";

const AUTO_DIRECTIONS = ["LONG", "SHORT", "BOTH"];

export default function AutoTradingPage({
  view,
  symbols,
  auto,
  setAuto,
  onEmergencyStop,
  autoDecision,
  selectedDetail,
  selectedRisk,
  selectedPaperTradeCandidate,
  openTrades,
  onExecutePaperTrades,
}) {
  const state = autoTradingState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
  const executor = executorState(selectedPaperTradeCandidate);
  const warningPills = dedupeReasonList(autoDecision.warnings || []);
  const reasonPills = dedupeReasonList(autoDecision.reasons || []);
  const executorBlockedReasons = dedupeReasonList(selectedPaperTradeCandidate?.blocked_reasons || []);
  const scopedBlockers = [
    {
      key: "trade",
      label: "Trade-level",
      reasons: dedupeReasonList([
        ...(autoDecision.blockerScopes?.trade || autoDecision.tradeBlockers || []),
        ...(selectedPaperTradeCandidate?.blocker_scopes?.trade || []),
      ]),
    },
    {
      key: "coin",
      label: "Coin-level",
      reasons: dedupeReasonList([
        ...(autoDecision.blockerScopes?.coin || autoDecision.coinBlockers || []),
        ...(selectedPaperTradeCandidate?.blocker_scopes?.coin || []),
      ]),
    },
    {
      key: "account",
      label: "Account-level",
      reasons: dedupeReasonList([
        ...(autoDecision.blockerScopes?.account || autoDecision.accountBlockers || []),
        ...(selectedPaperTradeCandidate?.blocker_scopes?.account || []),
      ]),
    },
  ];
  const hasScopedBlockers = scopedBlockers.some((scope) => scope.reasons.length);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-3 py-3 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-1.5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Futures Auto Trading</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Futures automation lock and eligibility</h2>
          </div>
          <div className="flex flex-wrap gap-1.5 sm:gap-2">
            <Pill tone="cyan">PAPER ONLY</Pill>
            {auto.version ? <Pill tone="slate">POLICY v{auto.version}</Pill> : null}
            {autoDecision.stackState ? <Pill tone={autoDecision.stackState === "ALIGNED" ? "emerald" : autoDecision.stackState === "MIXED_STRONG" ? "rose" : "amber"}>{autoDecision.stackState}</Pill> : null}
            <Pill tone={state.tone}>{state.label}</Pill>
            <Pill tone={auto.locked ? "amber" : "emerald"}>{auto.locked ? "LOCKED" : "UNLOCKED"}</Pill>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 sm:gap-3 xl:grid-cols-5">
          <MetricCard label="Auto status" value={state.label} note={state.note} icon={state.icon} accent={state.tone} />
          <MetricCard
            label="Selected signal"
            value={selectedDetail.signalType || "WAIT"}
            note={formatPercent(selectedDetail.confidence, 0, "-")}
            icon={Bot}
            accent={selectedDetail.signalType === "BUY" ? "emerald" : selectedDetail.signalType === "SELL" ? "rose" : "slate"}
          />
          <MetricCard
            label="Allowed contract"
            value={auto.allowedSymbols.includes(view.symbol) ? "Yes" : "No"}
            note={view.symbol}
            icon={ShieldCheck}
            accent={auto.allowedSymbols.includes(view.symbol) ? "emerald" : "rose"}
          />
          <MetricCard
            label="Executor verdict"
            value={executor.label}
            note={executor.note}
            icon={executor.icon}
            accent={executor.tone}
          />
          <MetricCard
            className="col-span-2 xl:col-span-1"
            label="Selected coin trades"
            value={openTrades.length}
            note={`${view.symbol} · account limit ${auto.maxOpenTrades}`}
            icon={Wallet}
            accent={openTrades.length < auto.maxOpenTrades ? "emerald" : "rose"}
          />
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <DiagnosticStrip
            label="Auto gate"
            value={state.label}
            note={state.note}
            tone={state.tone}
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
            label="Timing state"
            value={humanizeMachineStatus(selectedDetail.timing?.trigger?.status || selectedDetail.entryTrigger?.trigger?.status, "Unknown")}
            note={selectedDetail.timing?.trigger?.reason || selectedDetail.entryTrigger?.trigger?.reason || selectedDetail.prediction?.setup?.reason || "No timing explanation available"}
            tone={timingTone(selectedDetail.timing?.trigger?.status || selectedDetail.entryTrigger?.trigger?.status)}
          />
        </div>

        <div className="mt-3">
          <Phase2ValidationBadge
            symbol={view.symbol}
            timeframe={view.timeframe || "1h"}
            signalType={selectedDetail.signalType}
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

        <div className="mt-3 grid items-start gap-3 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="self-start rounded-lg border border-white/10 bg-slate-900/70 p-2">
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
                {auto.locked ? "Unlock futures auto trading" : "Lock futures auto trading"}
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

              <button
                type="button"
                onClick={onExecutePaperTrades}
                className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-cyan-400/30 bg-cyan-500/10 px-3.5 py-2 text-sm font-medium text-cyan-200 transition hover:bg-cyan-500/20"
              >
                Run futures paper-trade executor
              </button>
              <div className="mt-2 text-[11px] leading-5 text-slate-500">
                Scheduler cadence: every 60 seconds. Manual execution refreshes futures paper-trade decisions immediately.
              </div>

            <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/70 p-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Timing reason</div>
              <div className="mt-1.5 line-clamp-2 text-sm leading-5 text-slate-200">{state.note}</div>
            </div>

            <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/70 p-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Executor truth</div>
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

            <div
              className={clsx(
                "mt-3 rounded-lg border px-3 py-2.5",
                selectedDetail.timing?.trigger?.status === "WAIT" || selectedDetail.entryTrigger?.trigger?.status === "WAIT"
                  ? "border-amber-400/20 bg-amber-500/10 text-amber-100"
                  : "border-emerald-400/20 bg-emerald-500/10 text-emerald-100"
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-medium">
                  {selectedDetail.timing?.trigger?.status === "WAIT" || selectedDetail.entryTrigger?.trigger?.status === "WAIT" ? "Waiting for timing confirmation" : "Execution-ready"}
                </div>
                <Pill tone={selectedDetail.timing?.trigger?.status === "WAIT" || selectedDetail.entryTrigger?.trigger?.status === "WAIT" ? "amber" : "emerald"}>
                  {humanizeMachineStatus(selectedDetail.timing?.trigger?.status || selectedDetail.entryTrigger?.trigger?.status, "Unknown")}
                </Pill>
              </div>
              <div className="mt-1.5 text-xs leading-5 opacity-90">
                {selectedDetail.timing?.trigger?.reason || selectedDetail.entryTrigger?.trigger?.reason || selectedDetail.prediction?.setup?.reason || selectedDetail.tradeSetup?.setup?.reason || "No execution reason available"}
              </div>
            </div>
          </div>

          <div className="self-start rounded-lg border border-white/10 bg-slate-900/70 p-2">
            <div className="flex flex-wrap items-center justify-between gap-2.5">
              <div>
                <div className="text-sm font-medium text-white">Eligibility controls</div>
                <div className="text-xs text-slate-500">Contract allowlist and direction gates</div>
              </div>
              <Pill tone={state.tone}>{state.label}</Pill>
            </div>

            <div className="mt-3 grid gap-2.5 lg:grid-cols-2">
              <ControlBlock label="Allowed contracts" value={auto.allowedSymbols.join(", ") || "None"}>
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
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Scoped risk blockers</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {warningPills.length ? (
                  warningPills.map((warning) => (
                    <Pill key={warning} tone="amber">
                      {warning}
                    </Pill>
                  ))
                ) : null}
                {!hasScopedBlockers && reasonPills.length ? (
                  reasonPills.map((reason) => <Pill key={reason} tone="rose">{reason}</Pill>)
                ) : !hasScopedBlockers ? (
                  <Pill tone="emerald">No rule violations</Pill>
                ) : null}
              </div>
              {hasScopedBlockers ? (
                <div className="mt-2 grid gap-2 md:grid-cols-3">
                  {scopedBlockers.map((scope) => (
                    <div key={scope.key} className="rounded-lg border border-white/10 bg-slate-900/60 p-2">
                      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{scope.label}</div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {scope.reasons.length
                          ? scope.reasons.map((reason) => <Pill key={reason} tone="rose">{reason}</Pill>)
                          : <Pill tone="emerald">Clear</Pill>}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
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

function LifecyclePanel({ stages = [] }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2.5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Paper-trade lifecycle</div>
          <div className="text-xs text-slate-500">Where the selected setup currently sits in the execution pipeline</div>
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

function autoTradingState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades }) {
  const state = deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
  if (state.label === "Emergency stop") return { ...state, icon: PauseCircle };
  if (state.label === "Auto trading locked") return { ...state, icon: Lock };
  if (state.label === "Blocked by confidence") return { ...state, icon: ShieldCheck };
  if (state.label === "Blocked by risk") return { ...state, icon: ShieldCheck };
  if (state.label === "Ready to execute" || state.label === "Eligible") return { ...state, icon: Unlock };
  return { ...state, icon: Bot };
}

function executorState(candidate) {
  if (!candidate) {
    return {
      label: "No queued plan",
      note: "Executor has no OPEN trade plan queued for this symbol yet, so UI eligibility alone will not start a paper trade.",
      tone: "amber",
      icon: Bot,
    };
  }

  if (candidate.eligible) {
    return {
      label: "Executor ready",
      note: "Queued OPEN trade plan passes executor checks and can be opened by the paper-trade executor.",
      tone: "emerald",
      icon: Unlock,
    };
  }

  return {
    label: "Executor blocked",
    note: candidate.blocked_reasons?.[0] || "Queued trade plan is blocked by executor checks.",
    tone: "rose",
    icon: ShieldCheck,
  };
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
          ? (riskStale ? `Executor needs a fresh risk decision before treating this candidate as ready.` : (selectedPaperTradeCandidate?.blocked_reasons?.[0] || "Queued candidate is blocked by executor checks."))
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
