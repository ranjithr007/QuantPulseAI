import { useEffect, useState } from "react";
import clsx from "clsx";
import ExitPolicyEvidence from "../components/ExitPolicyEvidence";
import TradeAuditDialog from "../components/TradeAuditDialog";
import { preTargetLosingStops } from "../utils/tradeAudit";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Layers3,
  RefreshCw,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { loadStrategyLedger, loadStrategySummary } from "../hooks/dashboardApi";
import { formatPercent, formatSigned, formatTimeInIst } from "../utils/formatters";
import { requestFailureMessage, retryDelay } from "../utils/requestRecovery";
import { startVisiblePolling } from "../utils/visiblePolling";

const STRATEGY_GRID_PAGE_SIZE = 5;

export default function StrategiesPage() {
  const [payload, setPayload] = useState({ records: [] });
  const [loading, setLoading] = useState(true);
  const [ledgerLoading, setLedgerLoading] = useState(true);
  const [error, setError] = useState("");
  const [ledgerError, setLedgerError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [summaryLoadedAt, setSummaryLoadedAt] = useState(null);
  const [ledgerLoadedAt, setLedgerLoadedAt] = useState(null);
  const [now, setNow] = useState(Date.now());
  const [paused, setPaused] = useState(document.visibilityState === "hidden");
  const records = payload?.records || [];
  const initialLoading = loading && !records.length;

  useEffect(() => {
    let failures = 0;
    return startVisiblePolling(async (signal) => {
      setLoading(true);
      setLedgerLoading(true);
      let section = "summary";
      try {
        const response = await loadStrategySummary({
          includeLedger: false,
          signal,
        });
        if (signal.aborted) return null;
        setPayload((current) => preserveLoadedLedger(response, current));
        setSummaryLoadedAt(Date.now());
        setError("");
        setLoading(false);
        section = "ledger";
        const ledger = await loadStrategyLedger({ signal });
        if (signal.aborted) return null;
        setPayload((current) => mergeStrategyLedger(current, ledger));
        setLedgerLoadedAt(Date.now());
        setLedgerError("");
        failures = 0;
        return 60000;
      } catch (requestError) {
        if (signal.aborted) return null;
        const delay = retryDelay(requestError, ++failures);
        const message = requestFailureMessage(requestError, section === "summary" ? "Strategy decisions" : "Strategy Paper history");
        (section === "summary" ? setError : setLedgerError)(message + (delay != null ? ` Retrying automatically in ${delay / 1000} seconds.` : ""));
        return delay;
      } finally {
        if (!signal.aborted) {
          setLoading(false);
          setLedgerLoading(false);
          setNow(Date.now());
        }
      }
    });
  }, [refreshKey]);

  useEffect(() => {
    let timer;
    const update = () => {
      window.clearInterval(timer);
      const hidden = document.visibilityState === "hidden";
      setPaused(hidden);
      setNow(Date.now());
      if (!hidden) timer = window.setInterval(() => setNow(Date.now()), 15000);
    };
    update();
    document.addEventListener("visibilitychange", update);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", update); };
  }, []);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Paper strategy laboratory</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Strategies</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-400">
              Every strategy runs an isolated Strategy Paper book for fair comparison, while eligible plans also compete for one consolidated paper position per coin.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setRefreshKey((value) => value + 1)}
            disabled={loading || ledgerLoading}
            aria-busy={loading || ledgerLoading}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/10 bg-slate-900 px-3 text-sm text-slate-200 hover:border-cyan-400/30 disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw className={clsx("h-4 w-4", loading && "animate-spin")} /> {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        <div role="status" className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
          {paused ? "Automatic refresh paused while hidden." : "Automatic refresh every 60 seconds after each completed cycle."}
          <span className="ml-2">Decisions loaded: {summaryLoadedAt ? formatTimeInIst(summaryLoadedAt) : "Not yet loaded"}{summaryLoadedAt && (error || now - summaryLoadedAt > 120000) ? " · STALE DISPLAY" : ""}.</span>
          <span className="ml-2">Wallet/history loaded: {ledgerLoadedAt ? formatTimeInIst(ledgerLoadedAt) : "Not yet loaded"}{ledgerLoadedAt && (ledgerError || now - ledgerLoadedAt > 120000) ? " · STALE DISPLAY" : ""}.</span>
          <span className="mt-1 block">These are page retrieval times, not signal generation times. Check each candidate’s Evaluated IST timestamp for evidence freshness.</span>
        </div>

        <div className="mt-3 rounded-lg border border-cyan-400/15 bg-cyan-500/5 px-3 py-2 text-xs leading-relaxed text-slate-400">
          A bullish or bearish score is directional evidence, not entry confirmation. The entry-only candidate tests confirmed price structure with immediate trailing; the exit-only candidate keeps baseline entries and tests trailing delayed until 1R. These isolated paper candidates leave incumbent baselines unchanged. Trade audits show recorded policies and structure evidence; missing historical values remain unknown.
        </div>

        {error ? (
          <div role="alert" className="mt-3 flex flex-col gap-2 rounded-lg border border-rose-400/20 bg-rose-500/10 p-3 text-sm text-rose-200 sm:flex-row sm:items-center sm:justify-between">
            <span>{error}{records.length ? " Showing the last successful strategy snapshot." : ""}</span>
            <button type="button" onClick={() => setRefreshKey((value) => value + 1)} className="self-start rounded-md border border-rose-300/30 px-2.5 py-1 text-xs font-semibold hover:bg-rose-400/10 sm:self-auto">Retry</button>
          </div>
          ) : null}
        {ledgerError ? (
          <div role="status" className="mt-3 rounded-lg border border-amber-400/20 bg-amber-500/10 p-3 text-sm text-amber-800">
            Current strategy decisions are available, but the Strategy Paper wallet and history could not refresh: {ledgerError}
          </div>
        ) : null}
        <ComparisonBanner comparison={payload?.comparison} />
        <div className="mt-4 space-y-4">
          {initialLoading ? (
            <div className="rounded-xl border border-sky-200 bg-white p-8 text-center text-sm text-slate-500 shadow-sm">
              Loading governed paper strategies…
            </div>
          ) : null}
          {records.map((strategy) => (
            <StrategyPanel
              key={`${strategy.id}:${strategy.version}`}
              strategy={strategy}
              ledgerLoading={ledgerLoading && strategy.ledger_loaded === false}
            />
          ))}
          {!loading && !error && !records.length ? (
            <div className="rounded-xl border border-white/10 bg-slate-900/70 p-8 text-center text-sm text-slate-400">No governed paper strategies are registered.</div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function strategyKey(strategy) {
  return `${strategy?.id || ""}:${strategy?.version || ""}`;
}

function preserveLoadedLedger(response, current) {
  const previousByKey = new Map(
    (current?.records || [])
      .filter((strategy) => strategy.ledger_loaded)
      .map((strategy) => [strategyKey(strategy), strategy])
  );
  return {
    ...response,
    records: (response?.records || []).map((strategy) => {
      const previous = previousByKey.get(strategyKey(strategy));
      if (!previous) return strategy;
      return {
        ...strategy,
        ledger_loaded: true,
        strategy_paper_lifetime_performance: previous.strategy_paper_lifetime_performance,
        strategy_paper_wallet: previous.strategy_paper_wallet,
        strategy_paper_history: previous.strategy_paper_history,
      };
    }),
  };
}

function mergeStrategyLedger(current, ledger) {
  const ledgerByKey = new Map(
    (ledger?.records || []).map((strategy) => [strategyKey(strategy), strategy])
  );
  return {
    ...current,
    records: (current?.records || []).map((strategy) => ({
      ...strategy,
      ...(ledgerByKey.get(strategyKey(strategy)) || {}),
    })),
  };
}

function ComparisonBanner({ comparison }) {
  if (!comparison) return null;
  const ready = comparison.status === "EVIDENCE_READY";
  const leader = comparison.research_leader_strategy_id;
  return (
    <div className="mt-4 flex flex-col gap-2 rounded-xl border border-white/10 bg-slate-900/70 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Forward-test comparison</div>
        <div className="mt-1 text-sm font-medium text-white">
          {ready
            ? leader
              ? `Promotion candidate: ${leader}`
              : "Evidence complete, but no strategy passed every promotion gate"
            : `Collecting ${comparison.minimum_closed_trades_per_strategy || 30} closed Strategy Paper trades per strategy`}
        </div>
        <div className="mt-1 text-xs text-slate-500">Current ranking: {(comparison.ranking || []).join(" → ") || "waiting for data"}</div>
      </div>
      <StatusBadge label={comparison.status} tone={ready ? "emerald" : "amber"} />
    </div>
  );
}

function StrategyPanel({ strategy, ledgerLoading }) {
  const performance = strategy.strategy_paper_performance || strategy.performance || {};
  const officialPerformance = strategy.official_performance || {};
  const wallet = strategy.strategy_paper_wallet || {};
  const coverage = strategy.coverage || {};
  const readiness = strategy.forward_test_readiness || {};
  const learning = strategy.learning_evaluation || {};
  return (
    <article className="overflow-hidden rounded-xl border border-white/10 bg-slate-900/70">
      <div className="border-b border-white/10 bg-gradient-to-r from-cyan-500/10 via-transparent to-transparent p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-semibold text-white">{strategy.name}</h3>
              <StatusBadge label={strategy.status} tone="emerald" />
              <StatusBadge label={strategy.strategy_type || "INDIVIDUAL"} tone={strategy.strategy_type === "COMBINED" ? "amber" : "slate"} />
              <StatusBadge label="PAPER ONLY" tone="cyan" />
              <StatusBadge
                label={strategy.read_only ? "READ-ONLY HISTORY" : strategy.official_execution_enabled ? "OFFICIAL PAPER LANE" : "STRATEGY PAPER ONLY"}
                tone={strategy.official_execution_enabled ? "emerald" : "slate"}
              />
              <StatusBadge
                label={readiness.status || "COLLECTING"}
                tone={readiness.status === "PROMOTION_CANDIDATE" ? "emerald" : readiness.status === "EVIDENCE_COMPLETE_FAILED" ? "rose" : "amber"}
              />
            </div>
            <p className="mt-1 max-w-3xl text-sm text-slate-400">{strategy.description}</p>
            <div className="mt-2 font-mono text-[11px] text-slate-500">{strategy.id} · {strategy.version}</div>
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-slate-950/55 px-3 py-2 text-xs text-slate-300">
            <ShieldCheck className="h-4 w-4 text-cyan-300" /> One active trade per coin
          </div>
        </div>
      </div>

      <div className="p-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <Metric label="Evaluations" value={coverage.decision_snapshots || 0} icon={Activity} />
          <Metric label="Eligible scans" value={coverage.eligible_signals || 0} icon={CheckCircle2} tone="emerald" />
          <Metric label="Blocked scans" value={coverage.blocked_signals || 0} icon={AlertTriangle} tone="amber" />
          <Metric label="Strategy Paper trades" value={performance.total_trades || 0} icon={Layers3} />
          <Metric label="Win rate" value={formatPercent(performance.win_rate || 0, 1)} icon={TrendingUp} tone="emerald" />
          <Metric label="Drawdown" value={formatPercent(performance.max_drawdown_percent || 0, 2)} icon={TrendingDown} tone="rose" />
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <ValueCard label="Strategy Paper net P&L" value={`₹${number(performance.net_pnl_inr, 2)}`} tone={performance.net_pnl_inr >= 0 ? "emerald" : "rose"} />
          <ValueCard label="Strategy Paper return" value={formatSigned(performance.account_return_percent || 0, 2) + "%"} tone={performance.account_return_percent >= 0 ? "emerald" : "rose"} />
          <ValueCard label="Gross trade P&L" value={formatSigned(performance.gross_trade_pnl_percent || 0, 2) + "%"} />
          <ValueCard label="Fees" value={formatPercent(performance.fees_percent || 0, 2)} tone="amber" />
          <ValueCard label="Funding cost" value={formatPercent(performance.funding_cost_percent || 0, 3)} tone="amber" />
          <ValueCard label="Profit factor" value={performance.profit_factor == null ? "—" : number(performance.profit_factor, 2)} />
          <ValueCard label="Consolidated winner trades" value={officialPerformance.total_trades || 0} tone="cyan" />
          <ValueCard label="Target successes" value={`${performance.target_successes || 0} · ${formatPercent(performance.target_success_rate || 0, 1)}`} tone="emerald" />
          <ValueCard label="Pre-T1 losing stops" value={preTargetLosingStops(performance) ?? "Not recorded"} tone="rose" />
          <ValueCard label="Protected stop exits" value={performance.protected_stop_exits || 0} tone="cyan" description="Includes stop exits after T1 and non-losing stop exits before T1. This aggregate is not proof that every stop was protected by a T1 event." />
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <ValueCard label="Strategy capital" value={ledgerLoading ? "Loading…" : `₹${number(wallet.initial_capital_inr || 200000, 2)}`} />
          <ValueCard label="Strategy wallet balance" value={ledgerLoading ? "Loading…" : `₹${number(wallet.wallet_balance_inr || 200000, 2)}`} tone={(wallet.realized_pnl_inr || 0) >= 0 ? "emerald" : "rose"} />
          <ValueCard label="Open Strategy Paper positions" value={ledgerLoading ? "Loading…" : wallet.open_position_count || 0} tone="cyan" />
        </div>

        <div className="mt-3 text-xs text-slate-500">
          Promotion requires {readiness.minimum_closed_trades || 30} closed Strategy Paper trades in a verified policy cohort, win rate ≥ {readiness.minimum_win_rate || 55}%, profit factor ≥ {number(readiness.minimum_profit_factor || 1.3, 2)}, positive cost-adjusted expectancy, target successes greater than pre-T1 losing stops, and drawdown ≤ {formatPercent(readiness.maximum_drawdown_percent || 10, 0)}. {readiness.remaining_trades || 0} trades remain for the sample gate. This never enables live orders automatically.
        </div>
        <div className="mt-1 text-xs text-slate-500">
          Eligible scans are evaluations, not separate positions. Repeated unchanged signals reuse the matching open plan or position; only one official paper winner may be active per coin.
        </div>

        {learning.status ? <StrategyLearningStatus learning={learning} /> : null}

        <CandidateTable candidates={strategy.candidates || []} />
        <StrategyPaperHistory trades={strategy.strategy_paper_history || []} loading={ledgerLoading} />
      </div>
    </article>
  );
}

function StrategyLearningStatus({ learning }) {
  const metrics = learning.metrics || {};
  const recommendations = learning.recommended_changes || {};
  const gates = metrics.gates || {};
  const gateEntries = Object.entries(gates);
  return (
    <div className="mt-4 rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Automatic paper learning</div>
          <div className="mt-1 text-sm font-semibold text-white">
            30-trade window at milestone {learning.milestone} · {learning.status.replaceAll("_", " ")}
          </div>
        </div>
        <StatusBadge label="LIVE DISABLED" tone="slate" />
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <ValueCard label="Targets / pre-T1 losing stops" value={`${metrics.target_successes || 0} / ${preTargetLosingStops(metrics) ?? "Unknown"}`} tone={preTargetLosingStops(metrics) != null && (metrics.target_successes || 0) > preTargetLosingStops(metrics) ? "emerald" : "rose"} />
        <ValueCard label="Window win rate" value={formatPercent(metrics.win_rate || 0, 1)} />
        <ValueCard label="Window expectancy" value={`₹${number(metrics.expectancy_inr || 0, 2)}`} tone={(metrics.expectancy_inr || 0) > 0 ? "emerald" : "rose"} />
        <ValueCard label="Candidate version" value={learning.candidate_version || "No new candidate version"} tone="cyan" />
      </div>
      {metrics.metric_version === "STOP_CAUSE_COHORT_V3" ? <div className="mt-3 rounded-lg border border-white/10 p-3">
        <div className="break-words text-xs text-slate-400">{metrics.cohort_verified ? `Verified policy cohort: ${metrics.cohort_key}` : "Legacy diagnostic only: policy cohort is not verified; cannot qualify a new exit policy."}</div>
        <div className="mt-1 text-xs text-slate-500">{metrics.cohort_closed_trades ?? 0} cohort closes · {metrics.unknown_cohort_trades ?? 0} unknown-policy closes excluded from verified cohort. Thirty closes are an initial checkpoint, not proof of a durable edge.</div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <ValueCard label="Verified initial-stop losses" value={metrics.initial_stop_failures ?? "Not recorded"} tone="rose" />
          <ValueCard label="Trailed exits before T1" value={metrics.trailed_stop_pre_t1_exits ?? "Not recorded"} />
          <ValueCard label="Protected exits after T1" value={metrics.protected_stop_after_t1_exits ?? "Not recorded"} tone="cyan" />
          <ValueCard label="Unclassified stop exits" value={metrics.unknown_stop_exits ?? "Not recorded"} tone="amber" />
        </div>
        {Object.keys(learning.diagnostics?.by_side || {}).length ? <div className="mt-2 overflow-x-auto"><table className="w-full text-left text-xs"><caption className="mb-1 text-left text-slate-500">Same policy cohort · direction breakdown</caption><thead><tr>{["Side", "Closed", "Win rate", "Net P&L", "Targets / pre-T1 losses"].map((label) => <th key={label} className="px-2 py-1 text-slate-500">{label}</th>)}</tr></thead><tbody>{Object.entries(learning.diagnostics.by_side).map(([side, values]) => <tr key={side}><td className="px-2 py-1">{side}</td><td className="px-2 py-1">{values.closed_trades ?? "Unknown"}</td><td className="px-2 py-1">{formatPercent(values.win_rate, 1)}</td><td className="px-2 py-1">₹{number(values.net_pnl_inr, 2)}</td><td className="px-2 py-1">{values.target_successes ?? "Unknown"} / {preTargetLosingStops(values) ?? "Unknown"}</td></tr>)}</tbody></table></div> : null}
      </div> : null}
      {gateEntries.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {gateEntries.map(([name, passed]) => (
            <StatusBadge key={name} label={`${name.replaceAll("_", " ")}: ${passed ? "PASS" : "FAIL"}`} tone={passed ? "emerald" : "rose"} />
          ))}
        </div>
      ) : null}
      {Object.keys(recommendations).length ? (
        <div className="mt-3 text-xs text-slate-500">
          Candidate filters: confidence ≥ {recommendations.minimum_confidence || 40}%
          {(recommendations.allowed_timeframes || []).length ? ` · timeframes ${(recommendations.allowed_timeframes || []).join(", ")}` : ""}
          {(recommendations.allowed_regimes || []).length ? ` · regimes ${(recommendations.allowed_regimes || []).join(", ")}` : ""}
          {(recommendations.blocked_symbols || []).length ? ` · quarantined ${(recommendations.blocked_symbols || []).join(", ")}` : ""}
        </div>
      ) : null}
    </div>
  );
}

function StrategyPaperHistory({ trades, loading = false }) {
  const pagination = usePaginatedRows(trades);
  const [auditTrade, setAuditTrade] = useState(null);
  return (
    <div className="mt-4 overflow-hidden rounded-xl border border-white/10">
      <div className="flex items-center justify-between border-b border-white/10 bg-slate-950/60 px-4 py-3">
        <div className="text-sm font-medium text-white">Recent Strategy Paper trades</div>
        <div className="text-xs text-slate-500">Isolated ₹200,000 strategy book</div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[1040px] w-full text-left text-xs">
          <thead className="bg-slate-950/40 text-[10px] uppercase tracking-[0.14em] text-slate-500">
            <tr><th className="px-4 py-2.5">Coin</th><th>Side / TF</th><th>Entry</th><th>Stop</th><th>Target 1</th><th>Target 2</th><th>Status</th><th>Exit</th><th>Net P&amp;L</th><th>Opened IST</th><th>Evidence</th></tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {pagination.visibleRows.map((trade) => (
              <tr key={trade.id} className="text-slate-300">
                <td className="px-4 py-3 font-semibold text-white">{trade.symbol}</td>
                <td><StatusBadge label={trade.side} tone={trade.side === "LONG" ? "emerald" : "rose"} /> <span className="ml-1">{trade.entry_timeframe || "—"}</span></td>
                <td>{price(trade.entry_price)}</td>
                <td><div>{price(trade.stop_loss)}</div><ExitPolicyEvidence trade={trade} /></td>
                <td>{price(trade.target1)}</td>
                <td>{price(trade.target2)}</td>
                <td><StatusBadge label={trade.status} tone={trade.status === "OPEN" ? "cyan" : trade.result === "WIN" ? "emerald" : "rose"} /></td>
                <td>{price(trade.exit_price)}</td>
                <td className={numberTone(trade.realized_pnl_inr)}>{trade.status === "OPEN" ? "Open" : `₹${number(trade.realized_pnl_inr, 2)} · ${formatSigned(trade.pnl_percent || 0, 2)}%`}</td>
                <td className="pr-4 text-slate-500"><span className="inline-flex items-center gap-1"><Clock3 className="h-3.5 w-3.5" />{formatTimeInIst(trade.opened_at)}</span></td>
                <td className="pr-3"><button type="button" className="rounded-md border border-white/10 px-2.5 py-1.5 text-xs" aria-label={`View strategy audit ${trade.symbol} trade ${trade.id}`} onClick={() => setAuditTrade(trade)}>View audit</button></td>
              </tr>
            ))}
            {loading ? <tr><td colSpan="11" className="px-4 py-8 text-center text-slate-500">Loading recent Strategy Paper trades…</td></tr> : null}
            {!loading && !trades.length ? <tr><td colSpan="11" className="px-4 py-8 text-center text-slate-500">No Strategy Paper trades recorded yet.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <GridPagination
        {...pagination}
        itemLabel="paper trades"
        ariaLabel="Strategy Paper trade history pagination"
      />
      {auditTrade ? <TradeAuditDialog trade={auditTrade} ledgerLabel="Isolated Strategy Paper ledger" onClose={() => setAuditTrade(null)} /> : null}
    </div>
  );
}

function CandidateTable({ candidates }) {
  const pagination = usePaginatedRows(candidates);
  return (
    <div className="mt-4 overflow-hidden rounded-xl border border-white/10">
      <div className="flex items-center justify-between border-b border-white/10 bg-slate-950/60 px-4 py-3">
        <div className="text-sm font-medium text-white">Latest candidate per coin</div>
        <div className="text-xs text-slate-500">Signal → Strategy Paper book → consolidated winner</div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[1080px] w-full text-left text-xs">
          <thead className="bg-slate-950/40 text-[10px] uppercase tracking-[0.14em] text-slate-500">
            <tr><th className="px-4 py-2.5">Coin</th><th>Side / TF</th><th>Score</th><th>Confidence</th><th>Strategy decision</th><th>Market Move</th><th>Strategy Paper</th><th>Consolidated</th><th>Reason</th><th>Evaluated IST</th></tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {pagination.visibleRows.map((candidate) => (
              <tr key={candidate.decision_snapshot_id} className="text-slate-300">
                <td className="px-4 py-3 font-semibold text-white">{candidate.symbol}</td>
                <td>{candidate.side || "—"} · {candidate.timeframe || "—"}</td>
                <td className={numberTone(candidate.score)}>{candidate.score === null || candidate.score === undefined ? "—" : formatSigned(candidate.score, 1)}</td>
                <td>{formatPercent(candidate.confidence || 0, 1)}</td>
                <td><StatusBadge label={candidate.decision} tone={candidate.decision === "ELIGIBLE" ? "emerald" : "rose"} /></td>
                <td><StatusBadge label={candidate.market_participation?.direction || candidate.market_participation?.status || "N/A"} tone={directionTone(candidate.market_participation?.direction)} /></td>
                <td>{(candidate.strategy_paper_lifecycle || candidate.shadow_lifecycle)?.replaceAll("_", " ")}</td>
                <td>{candidate.lifecycle?.replaceAll("_", " ")}</td>
                <td className="max-w-[340px] py-3 pr-3 text-slate-400">
                  <div>{candidate.blocked_reasons?.[0] || candidate.market_participation?.reason || "All current strategy gates passed"}</div>
                  {candidate.regime_route ? <div className="mt-1 text-[10px] uppercase tracking-[0.1em] text-cyan-600">{candidate.regime_route.replaceAll("_", " ")}</div> : null}
                  {candidate.entry_location?.zone ? <div className="mt-0.5 text-[10px] text-slate-500">{candidate.entry_location.zone} · {candidate.entry_location.tests || 0} tests · {candidate.entry_location.rejection_confirmed ? "rejection confirmed" : "waiting for rejection"}</div> : null}
                </td>
                <td className="pr-4 text-slate-500"><span className="inline-flex items-center gap-1"><Clock3 className="h-3.5 w-3.5" />{formatTimeInIst(candidate.created_at)}</span></td>
              </tr>
            ))}
            {!candidates.length ? <tr><td colSpan="10" className="px-4 py-8 text-center text-slate-500">Waiting for the next strategy scan.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <GridPagination
        {...pagination}
        itemLabel="candidates"
        ariaLabel="Latest strategy candidates pagination"
      />
    </div>
  );
}

function GridPagination({
  ariaLabel,
  currentPage,
  firstVisible,
  itemLabel,
  lastVisible,
  setCurrentPage,
  totalItems,
  totalPages,
  visiblePageNumbers,
}) {
  if (!totalItems) return null;

  return (
    <div className="flex flex-col gap-2 border-t border-white/10 bg-slate-950/35 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="text-xs text-slate-500">
        Showing {firstVisible}–{lastVisible} of {totalItems} {itemLabel}
      </div>
      <nav className="flex flex-wrap items-center gap-1" aria-label={ariaLabel}>
        <PaginationButton
          disabled={currentPage === 1}
          label="Previous"
          onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
        />
        {visiblePageNumbers.map((page) => (
          <PaginationButton
            key={page}
            active={page === currentPage}
            label={String(page)}
            onClick={() => setCurrentPage(page)}
          />
        ))}
        <PaginationButton
          disabled={currentPage === totalPages}
          label="Next"
          onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
        />
      </nav>
    </div>
  );
}

function PaginationButton({ active = false, disabled = false, label, onClick }) {
  return (
    <button
      type="button"
      className={clsx(
        "min-w-8 rounded-md border px-2.5 py-1.5 text-xs font-medium transition",
        active
          ? "border-cyan-400/40 bg-cyan-500/15 text-cyan-200"
          : "border-white/10 bg-slate-950/40 text-slate-300 hover:border-cyan-400/30 hover:text-white",
        disabled && "cursor-not-allowed opacity-40 hover:border-white/10 hover:text-slate-300"
      )}
      disabled={disabled}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function usePaginatedRows(rows) {
  const totalItems = rows.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / STRATEGY_GRID_PAGE_SIZE));
  const [currentPage, setCurrentPage] = useState(1);
  const pageStart = (currentPage - 1) * STRATEGY_GRID_PAGE_SIZE;

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages));
  }, [totalPages]);

  return {
    currentPage,
    firstVisible: totalItems ? pageStart + 1 : 0,
    lastVisible: Math.min(pageStart + STRATEGY_GRID_PAGE_SIZE, totalItems),
    setCurrentPage,
    totalItems,
    totalPages,
    visiblePageNumbers: paginationPageNumbers(currentPage, totalPages),
    visibleRows: rows.slice(pageStart, pageStart + STRATEGY_GRID_PAGE_SIZE),
  };
}

function paginationPageNumbers(currentPage, totalPages) {
  const maximumVisiblePages = 5;
  const firstPage = Math.max(1, Math.min(currentPage - 2, totalPages - maximumVisiblePages + 1));
  const lastPage = Math.min(totalPages, firstPage + maximumVisiblePages - 1);
  return Array.from({ length: lastPage - firstPage + 1 }, (_, index) => firstPage + index);
}

function Metric({ label, value, icon: Icon, tone = "cyan" }) {
  return <div className="rounded-lg border border-white/10 bg-slate-950/55 p-3"><div className="flex items-center justify-between text-[10px] uppercase tracking-[0.14em] text-slate-500"><span>{label}</span><Icon className={clsx("h-4 w-4", toneClass(tone))} /></div><div className="mt-2 text-xl font-semibold text-white">{value}</div></div>;
}

function ValueCard({ label, value, tone = "slate", description }) {
  return <div className="rounded-lg border border-white/10 bg-slate-950/45 px-3 py-2.5"><div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}{description ? <span tabIndex={0} title={description} aria-label={description} className="ml-1 inline-block cursor-help rounded-full border border-slate-500 px-1 normal-case focus:outline-cyan-400">i</span> : null}</div><div className={clsx("mt-1 text-sm font-semibold", toneClass(tone))}>{value}</div></div>;
}

function StatusBadge({ label, tone = "slate" }) {
  return <span className={clsx("inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em]", badgeClass(tone))}>{label || "N/A"}</span>;
}

function badgeClass(tone) {
  if (tone === "emerald") return "border-emerald-400/20 bg-emerald-500/10 text-emerald-300";
  if (tone === "rose") return "border-rose-400/20 bg-rose-500/10 text-rose-300";
  if (tone === "amber") return "border-amber-400/20 bg-amber-500/10 text-amber-300";
  if (tone === "cyan") return "border-cyan-400/20 bg-cyan-500/10 text-cyan-300";
  return "border-white/10 bg-white/5 text-slate-300";
}

function toneClass(tone) {
  if (tone === "emerald") return "text-emerald-300";
  if (tone === "rose") return "text-rose-300";
  if (tone === "amber") return "text-amber-300";
  if (tone === "cyan") return "text-cyan-300";
  return "text-slate-200";
}

function directionTone(direction) {
  if (direction === "BULLISH") return "emerald";
  if (direction === "BEARISH") return "rose";
  return "amber";
}

function numberTone(value) {
  const numeric = Number(value || 0);
  return numeric > 0 ? "text-emerald-300" : numeric < 0 ? "text-rose-300" : "text-slate-400";
}

function number(value, digits) {
  return Number(value || 0).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function price(value) {
  if (value === null || value === undefined) return "—";
  const numeric = Number(value);
  const digits = numeric < 1 ? 6 : numeric < 100 ? 4 : 2;
  return numeric.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
