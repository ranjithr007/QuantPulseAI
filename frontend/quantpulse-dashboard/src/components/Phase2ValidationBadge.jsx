import { useEffect, useMemo, useState } from "react";
import Pill from "./ui/Pill";
import {
  loadPaperTradeLifecycleFunnel,
  loadPaperTradeMeasurement,
  loadPaperTradeOpportunities,
  loadPaperTradeRecoveryEvents,
  loadPhase2EvidenceCheckpoints,
  loadPhase2RollingValidation,
  loadWalkForwardSummary,
} from "../hooks/dashboardApi";

export default function Phase2ValidationBadge({ symbol, timeframe = "1h", signalType, className = "" }) {
  const [summary, setSummary] = useState(null);
  const [measurement, setMeasurement] = useState(null);
  const [opportunities, setOpportunities] = useState(null);
  const [lifecycleFunnel, setLifecycleFunnel] = useState(null);
  const [rollingValidation, setRollingValidation] = useState(null);
  const [recoveryHistory, setRecoveryHistory] = useState(null);
  const [dailyCheckpoints, setDailyCheckpoints] = useState(null);
  const [opportunityError, setOpportunityError] = useState("");
  const [opportunityDetailWarning, setOpportunityDetailWarning] = useState("");
  const [opportunityLoading, setOpportunityLoading] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const signalSide = useMemo(() => {
    if (signalType === "BUY") return "LONG";
    if (signalType === "SELL") return "SHORT";
    return null;
  }, [signalType]);

  const result = summary?.result || null;
  const contract = result?.validation_contract || null;
  const paperReport = measurement?.report || null;
  const paperOverall = paperReport?.overall || null;
  const scenarioAccuracy = paperReport?.scenario_accuracy || null;
  const regimeAccuracy = paperReport?.regime_accuracy || null;

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      if (!symbol || !signalSide) {
        setSummary(null);
        setMeasurement(null);
        setError("");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError("");

      try {
        const response = await loadWalkForwardSummary({
          symbol,
          signalSide,
          timeframe,
          signal: controller.signal,
        });

        if (!cancelled) {
          setSummary(response);
        }
      } catch (err) {
        if (!cancelled && err?.name !== "AbortError") {
          setSummary(null);
          setError(err instanceof Error ? err.message : "Unable to load Phase 2 validation status");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [symbol, timeframe, signalSide]);

  useEffect(() => {
    let cancelled = false;
    let controller = null;
    let timer = null;
    let inFlight = false;

    async function refreshMeasurement() {
      if (!symbol || !signalSide) {
        setMeasurement(null);
        return;
      }
      if (cancelled || inFlight || document.visibilityState === "hidden") return;

      inFlight = true;
      controller = new AbortController();
      try {
        const response = await loadPaperTradeMeasurement({
          symbol,
          signal: controller.signal,
        });
        if (!cancelled) setMeasurement(response);
      } catch (err) {
        if (!cancelled && err?.name !== "AbortError") setMeasurement(null);
      } finally {
        inFlight = false;
        if (!cancelled && document.visibilityState !== "hidden") {
          timer = window.setTimeout(refreshMeasurement, 60_000);
        }
      }
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "hidden") {
        if (timer) window.clearTimeout(timer);
        timer = null;
        controller?.abort();
        return;
      }
      if (timer) window.clearTimeout(timer);
      timer = null;
      refreshMeasurement();
    }

    refreshMeasurement();
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      cancelled = true;
      controller?.abort();
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [symbol, signalSide]);

  useEffect(() => {
    let cancelled = false;
    let controller = null;
    let timer = null;
    let inFlight = false;

    async function refreshOpportunities(includeDetails = false) {
      if (!symbol) {
        setOpportunities(null);
        setLifecycleFunnel(null);
        setRollingValidation(null);
        setRecoveryHistory(null);
        setDailyCheckpoints(null);
        setOpportunityError("");
        setOpportunityDetailWarning("");
        setOpportunityLoading(false);
        return;
      }
      if (cancelled || inFlight || document.visibilityState === "hidden") return;

      inFlight = true;
      controller = new AbortController();
      setOpportunityLoading(true);
      setOpportunityError("");
      setOpportunityDetailWarning("");
      try {
        const requests = [
          {
            label: "Opportunity totals",
            primary: true,
            request: loadPaperTradeOpportunities({ sinceHours: 24, signal: controller.signal }),
            apply: setOpportunities,
          },
          ...(includeDetails ? [{
            label: "Lifecycle funnel",
            request: loadPaperTradeLifecycleFunnel({ sinceHours: 24, signal: controller.signal }),
            apply: setLifecycleFunnel,
          },
          {
            label: "Rolling validation",
            request: loadPhase2RollingValidation({ signal: controller.signal }),
            apply: setRollingValidation,
          },
          {
            label: "Recovery history",
            request: loadPaperTradeRecoveryEvents({ limit: 20, signal: controller.signal }),
            apply: setRecoveryHistory,
          },
          {
            label: "Daily checkpoints",
            request: loadPhase2EvidenceCheckpoints({ limit: 30, signal: controller.signal }),
            apply: setDailyCheckpoints,
          }] : []),
        ];
        const results = await Promise.allSettled(
          requests.map((item) =>
            item.request.then((value) => {
              if (!cancelled) item.apply(value);
              return value;
            })
          )
        );
        if (!cancelled) {
          const failures = results
            .map((result, index) => ({ result, request: requests[index] }))
            .filter(({ result }) => result.status === "rejected");
          const primaryFailure = failures.find(({ request }) => request.primary);
          const detailFailures = failures
            .filter(({ request }) => !request.primary)
            .map(({ request }) => request.label);

          if (primaryFailure) {
            const reason = primaryFailure.result.reason;
            setOpportunities(null);
            setOpportunityError(
              reason instanceof Error ? reason.message : "Unable to load opportunity totals"
            );
          }
          setOpportunityDetailWarning(
            detailFailures.length
              ? `${detailFailures.join(", ")} unavailable; primary opportunity totals remain visible.`
              : ""
          );
        }
      } catch (err) {
        if (!cancelled && err?.name !== "AbortError") {
          setOpportunities(null);
          setLifecycleFunnel(null);
          setRollingValidation(null);
          setRecoveryHistory(null);
          setDailyCheckpoints(null);
          setOpportunityDetailWarning("");
          setOpportunityError(
            err instanceof Error ? err.message : "Unable to load opportunity accounting"
          );
        }
      } finally {
        inFlight = false;
        if (!cancelled) setOpportunityLoading(false);
        if (!cancelled && document.visibilityState !== "hidden") {
          timer = window.setTimeout(
            () => refreshOpportunities(true),
            includeDetails ? 5 * 60_000 : 15_000
          );
        }
      }
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "hidden") {
        if (timer) window.clearTimeout(timer);
        timer = null;
        controller?.abort();
        return;
      }
      if (timer) window.clearTimeout(timer);
      timer = null;
      refreshOpportunities(false);
    }

    refreshOpportunities(false);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      cancelled = true;
      controller?.abort();
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [symbol]);

  if (!signalSide) {
    return (
      <div className={`rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5 ${className}`}>
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Phase 2 validation</div>
            <div className="mt-1 text-xs text-slate-400">Waiting for BUY or SELL signal</div>
          </div>
          <Pill tone="slate">Idle</Pill>
        </div>
        <OpportunityEvidence report={opportunities} lifecycleFunnel={lifecycleFunnel} rollingValidation={rollingValidation} recoveryHistory={recoveryHistory} dailyCheckpoints={dailyCheckpoints} error={opportunityError} warning={opportunityDetailWarning} loading={opportunityLoading} />
      </div>
    );
  }

  return (
    <div className={`rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5 ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Phase 2 validation</div>
          <div className="mt-1 text-xs text-slate-400">
            {symbol} {signalSide} · {timeframe}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Pill tone={loading ? "amber" : contractTone(contract?.contract_status)}>{loading ? "Loading" : contract?.contract_status || "Pending"}</Pill>
          {contract?.timeframe_status ? <Pill tone={timeframeTone(contract.timeframe_status)}>{contract.timeframe_status}</Pill> : null}
        </div>
      </div>

      {error ? <div className="mt-2 text-xs text-rose-300">{error}</div> : null}

      {!error ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
          <span>Folds: {result?.fold_count ?? "-"}</span>
          <span>Min required: {contract?.minimum_fold_requirement ?? "-"}</span>
          <span>Config match: {contractLabel(contract?.configuration_matches_contract)}</span>
        </div>
      ) : null}

      {!error && paperReport ? (
        <div className="mt-2 rounded-md border border-white/10 bg-slate-900/60 px-2.5 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Official paper evidence</span>
            <Pill tone={measurementTone(paperReport.status)}>{paperReport.status || "Pending"}</Pill>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400">
            <span>Closed: {paperOverall?.closed_trades ?? 0}</span>
            <span>Days: {paperOverall?.observation_days ?? 0}</span>
            <span>Scenario: {accuracyLabel(scenarioAccuracy)}</span>
            <span>Regime: {accuracyLabel(regimeAccuracy)}</span>
          </div>
          <PromotionProgress report={paperReport} />
        </div>
      ) : null}

      <OpportunityEvidence report={opportunities} lifecycleFunnel={lifecycleFunnel} rollingValidation={rollingValidation} recoveryHistory={recoveryHistory} dailyCheckpoints={dailyCheckpoints} error={opportunityError} warning={opportunityDetailWarning} loading={opportunityLoading} />

      {!error && contract?.issues?.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {contract.issues.slice(0, 2).map((issue) => (
            <Pill key={issue} tone={issueTone(issue)}>
              {humanizeIssue(issue)}
            </Pill>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PromotionProgress({ report }) {
  const overall = report?.overall || {};
  const targets = report?.policy?.roadmap_targets || {};
  const closed = Number(overall.closed_trades || 0);
  const days = Number(overall.observation_days || 0);
  const closedTarget = Number(targets.min_closed_trades || 100);
  const daysTarget = Number(targets.min_observation_days || 90);

  return (
    <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
      <PromotionMetric
        label="Closed-trade evidence"
        value={closed}
        target={closedTarget}
      />
      <PromotionMetric
        label="Observation period"
        value={days}
        target={daysTarget}
        suffix=" days"
      />
    </div>
  );
}

function PromotionMetric({ label, value, target, suffix = "" }) {
  const progress = target > 0 ? Math.min(100, Math.max(0, (value / target) * 100)) : 0;

  return (
    <div className="rounded border border-white/10 bg-slate-950/60 px-2 py-1.5">
      <div className="flex items-center justify-between gap-2 text-[10px]">
        <span className="uppercase tracking-[0.1em] text-slate-500">{label}</span>
        <span className="shrink-0 text-slate-300">{value}{suffix} / {target}{suffix}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-cyan-400 transition-[width] duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

function OpportunityEvidence({ report, lifecycleFunnel, rollingValidation, recoveryHistory, dailyCheckpoints, error, warning, loading }) {
  if (loading && !report && !error) {
    return (
      <div className="mt-2 rounded-md border border-white/10 bg-slate-900/60 px-2.5 py-2">
        <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">24h opportunity accounting</div>
        <div className="mt-1 text-xs text-slate-400">Loading scheduled evaluations...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mt-2 rounded-md border border-rose-400/20 bg-rose-500/10 px-2.5 py-2 text-xs text-rose-200">
        <div>Opportunity accounting unavailable</div>
        <div className="mt-1 text-[11px] text-rose-300/80">{error}</div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mt-2 rounded-md border border-white/10 bg-slate-900/60 px-2.5 py-2">
        <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
          24h opportunity accounting
        </div>
        <div className="mt-1 text-xs text-slate-400">No opportunity accounting response is available yet.</div>
      </div>
    );
  }

  if (report.status !== "OK") {
    return (
      <div className="mt-2 rounded-md border border-rose-400/20 bg-rose-500/10 px-2.5 py-2 text-xs text-rose-200">
        Opportunity accounting status: {report.status || "UNKNOWN"}. {report.detail || "Scheduled evaluation data is unavailable."}
      </div>
    );
  }

  const reasons = Object.entries(report.by_block_reason || {}).slice(0, 3);
  const coverage = report.coverage || null;
  const coverageComplete = coverage?.status === "COMPLETE";

  return (
    <div className="mt-2 rounded-md border border-white/10 bg-slate-900/60 px-2.5 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-[0.16em] text-slate-500">
          24h opportunity accounting
        </span>
        <Pill tone={report.ready_count > 0 ? "emerald" : "amber"}>
          {report.ready_rate_percent ?? 0}% READY
        </Pill>
      </div>
      <div className="mt-1.5 grid grid-cols-3 gap-2 text-xs">
        <OpportunityMetric label="Evaluated" value={report.total_evaluations ?? 0} />
        <OpportunityMetric label="Ready" value={report.ready_count ?? 0} tone="emerald" />
        <OpportunityMetric label="Blocked" value={report.blocked_count ?? 0} tone="amber" />
      </div>
      {coverage ? (
        <div className={`mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md border px-2 py-1.5 ${coverageComplete ? "border-emerald-400/20 bg-emerald-500/10" : "border-rose-400/20 bg-rose-500/10"}`}>
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-slate-400">Evidence coverage</div>
            <div className="mt-0.5 text-xs text-slate-300">
              {coverage.recorded_evaluations ?? 0} / {coverage.expected_evaluations ?? 0} expected evaluations
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Pill tone={coverageComplete ? "emerald" : coverage?.status === "WAITING_FOR_GRACE_PERIOD" ? "amber" : "rose"}>
              {coverage.coverage_percent ?? 0}%
            </Pill>
            {coverage.missing_evaluations > 0 ? (
              <Pill tone="rose">{coverage.missing_evaluations} missing</Pill>
            ) : null}
          </div>
        </div>
      ) : null}
      {reasons.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {reasons.map(([reason, count]) => (
            <Pill key={reason} tone="slate">
              {humanizeIssue(reason)} · {count}
            </Pill>
          ))}
        </div>
      ) : null}
      {warning ? <div className="mt-2 text-[11px] text-amber-300">{warning}</div> : null}
      <LifecycleFunnel funnel={lifecycleFunnel} />
      <RollingValidation report={rollingValidation} />
      <DailyCheckpoint history={dailyCheckpoints} />
      <RecoveryHistory history={recoveryHistory} coverageComplete={coverageComplete} />
    </div>
  );
}

function RollingValidation({ report }) {
  if (!report || report.status !== "OK") return null;

  return (
    <div className="mt-2 rounded-md border border-violet-400/15 bg-violet-500/5 px-2 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-violet-300/70">
            Rolling proof-of-edge
          </div>
          <div className="mt-0.5 text-xs text-slate-400">Official 1h / 2h / 4h / 1d paper evidence only</div>
        </div>
        <Pill tone="slate">7d + 30d</Pill>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {(report.windows || []).map((window) => {
          const stages = window.stages || {};
          const performance = window.performance || {};
          return (
            <div key={window.days} className="min-w-0 rounded border border-white/10 bg-slate-950/60 px-2 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-semibold text-slate-200">Last {window.days} days</span>
                <Pill tone={measurementTone(window.status)}>{humanizeIssue(window.status || "Pending")}</Pill>
              </div>
              <div className="mt-2 grid grid-cols-4 gap-1 text-center">
                <RollingMetric label="Evaluated" value={stages.evaluated ?? 0} />
                <RollingMetric label="Ready" value={stages.ready ?? 0} />
                <RollingMetric label="Executed" value={stages.executed ?? 0} />
                <RollingMetric label="Closed" value={stages.closed ?? 0} />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-400">
                <span>Win rate <strong className="text-slate-200">{metricValue(performance.win_rate)}%</strong></span>
                <span>Profit factor <strong className="text-slate-200">{metricValue(performance.profit_factor)}</strong></span>
                <span>Expectancy <strong className="text-slate-200">{metricValue(performance.expectancy_percent)}%</strong></span>
                <span>Max DD <strong className="text-slate-200">{metricValue(performance.max_drawdown_percent)}%</strong></span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RollingMetric({ label, value }) {
  return (
    <div className="min-w-0 rounded bg-slate-900/70 px-1 py-1.5">
      <div className="truncate text-[9px] uppercase tracking-[0.08em] text-slate-500">{label}</div>
      <div className="mt-0.5 text-xs font-semibold text-slate-200">{value}</div>
    </div>
  );
}

function LifecycleFunnel({ funnel }) {
  if (!funnel || funnel.status === "UNAVAILABLE") return null;

  const executorBlockers = Object.entries(funnel.blockers?.executor || {})
    .sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0))
    .slice(0, 4);

  return (
    <div className="mt-2 rounded-md border border-cyan-400/15 bg-cyan-500/5 px-2 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-cyan-300/70">Live lifecycle funnel</div>
          <div className="mt-0.5 text-xs text-slate-300">{funnel.next_action}</div>
        </div>
        <Pill tone={lifecycleTone(funnel.status)}>{humanizeIssue(funnel.status)}</Pill>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-7">
        {(funnel.stages || []).map((stage) => (
          <div key={stage.key} className="rounded border border-white/10 bg-slate-950/60 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.1em] text-slate-500">{stage.label}</div>
            <div className="mt-0.5 text-sm font-semibold text-slate-100">{stage.count ?? 0}</div>
          </div>
        ))}
      </div>
      {executorBlockers.length ? (
        <div className="mt-2 rounded border border-amber-400/15 bg-amber-500/5 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.12em] text-amber-300/70">
            Why approved plans are not executor ready
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {executorBlockers.map(([reason, count]) => (
              <Pill key={reason} tone="amber">
                {humanizeIssue(reason)} · {count}
              </Pill>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function lifecycleTone(status) {
  if (["MONITORING", "EXECUTOR_READY"].includes(status)) return "emerald";
  if (["COVERAGE_GAP", "EXECUTOR_BLOCKED"].includes(status)) return "rose";
  return "amber";
}

function DailyCheckpoint({ history }) {
  const latest = history?.latest || null;
  const details = latest?.details || {};
  const measurement = details.measurement || {};

  if (!latest) {
    return (
      <div className="mt-2 rounded-md border border-white/10 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-400">
        Daily evidence checkpoint: pending first completed pipeline cycle
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-md border border-white/10 bg-slate-950/50 px-2 py-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-[0.12em] text-slate-500">Daily evidence · {details.checkpoint_date}</div>
          <div className="mt-0.5 text-xs text-slate-300">{latest.reason}</div>
        </div>
        <Pill tone={checkpointTone(latest.status)}>{latest.status}</Pill>
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-1.5 text-[11px] sm:grid-cols-4">
        <CheckpointMetric label="Closed" value={measurement.closed_trades ?? 0} />
        <CheckpointMetric label="Profit factor" value={metricValue(measurement.profit_factor)} />
        <CheckpointMetric label="Expectancy" value={`${metricValue(measurement.expectancy_percent)}%`} />
        <CheckpointMetric label="Drawdown" value={`${metricValue(measurement.max_drawdown_percent)}%`} />
      </div>
    </div>
  );
}

function CheckpointMetric({ label, value }) {
  return (
    <div className="min-w-0 rounded border border-white/10 px-1.5 py-1">
      <div className="truncate text-slate-500">{label}</div>
      <div className="mt-0.5 font-medium text-slate-200">{value}</div>
    </div>
  );
}

function checkpointTone(status) {
  if (status === "PASS") return "emerald";
  if (status === "ATTENTION") return "rose";
  return "amber";
}

function metricValue(value) {
  if (value === null || value === undefined) return "-";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : String(value);
}

function RecoveryHistory({ history, coverageComplete = false }) {
  const latest = history?.latest || null;
  const summary = history?.summary || {};

  if (!latest) {
    return (
      <div className="mt-2 rounded-md border border-white/10 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-400">
        Recovery history: no repair attempts required
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-md border border-white/10 bg-slate-950/50 px-2 py-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-[0.12em] text-slate-500">Recovery history</div>
          <div className="mt-0.5 text-xs text-slate-300">
            {coverageComplete
              ? "Current 24h coverage is complete; the event below is historical."
              : latest.reason}
          </div>
        </div>
        <Pill tone={coverageComplete ? "emerald" : recoveryTone(latest.status)}>
          {coverageComplete ? "CURRENTLY COMPLETE" : latest.status}
        </Pill>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
        {coverageComplete ? <span>Last historical outcome: {latest.status}</span> : null}
        <span>Attempts: {summary.attempts ?? 0}</span>
        <span>Recovered: {summary.recovered ?? 0}</span>
        <span>Unresolved: {(summary.unresolved ?? 0) + (summary.retry_failed ?? 0)}</span>
      </div>
    </div>
  );
}

function recoveryTone(status) {
  if (status === "RECOVERED") return "emerald";
  if (status === "UNRESOLVED" || status === "RETRY_FAILED") return "rose";
  return "amber";
}

function OpportunityMetric({ label, value, tone = "slate" }) {
  const valueClass = tone === "emerald"
    ? "text-emerald-300"
    : tone === "amber"
      ? "text-amber-300"
      : "text-white";

  return (
    <div className="min-w-0 rounded-md border border-white/10 bg-slate-950/60 px-2 py-1.5">
      <div className="truncate text-[10px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className={`mt-0.5 text-sm font-semibold ${valueClass}`}>{value}</div>
    </div>
  );
}

function contractTone(status) {
  if (status === "PASS") return "emerald";
  if (status === "PARTIAL" || status === "INSUFFICIENT_EVIDENCE") return "amber";
  if (status === "FAIL") return "rose";
  return "slate";
}

function measurementTone(status) {
  if (status === "PASS") return "emerald";
  if (status === "FAIL") return "rose";
  return "amber";
}

function accuracyLabel(accuracy) {
  if (!accuracy || accuracy.status !== "CALCULATED") return "Not started";
  return `${accuracy.accuracy_percent ?? 0}%`;
}

function timeframeTone(status) {
  if (status === "OFFICIAL") return "emerald";
  if (status === "SUPPORTING") return "amber";
  return "slate";
}

function issueTone(issue) {
  if (issue === "walk_forward_windows_do_not_match_phase2_contract") return "rose";
  if (issue === "minimum_fold_requirement_not_met" || issue === "insufficient_history_for_phase2_fold_requirement") return "amber";
  return "slate";
}

function contractLabel(value) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "N/A";
}

function humanizeIssue(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}
