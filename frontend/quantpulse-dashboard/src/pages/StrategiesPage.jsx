import { useEffect, useState } from "react";
import clsx from "clsx";
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
import { loadStrategySummary } from "../hooks/dashboardApi";
import { formatPercent, formatSigned, formatTimeInIst } from "../utils/formatters";

export default function StrategiesPage() {
  const [payload, setPayload] = useState({ records: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    loadStrategySummary({ signal: controller.signal })
      .then(setPayload)
      .catch((requestError) => {
        if (requestError?.name !== "AbortError") {
          setError(requestError?.message || "Strategy performance is unavailable");
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [refreshKey]);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Paper strategy laboratory</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Strategies</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-400">
              Core Signal and Market Move run independently, while Core Fusion evaluates their combined confirmation. Every eligible plan competes for one shared paper position per coin.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setRefreshKey((value) => value + 1)}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/10 bg-slate-900 px-3 text-sm text-slate-200 hover:border-cyan-400/30"
          >
            <RefreshCw className={clsx("h-4 w-4", loading && "animate-spin")} /> Refresh
          </button>
        </div>

        {error ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div> : null}
        <ComparisonBanner comparison={payload?.comparison} />
        <div className="mt-4 space-y-4">
          {(payload?.records || []).map((strategy) => <StrategyPanel key={`${strategy.id}:${strategy.version}`} strategy={strategy} />)}
          {!loading && !(payload?.records || []).length ? (
            <div className="rounded-xl border border-white/10 bg-slate-900/70 p-8 text-center text-sm text-slate-400">No governed paper strategies are registered.</div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ComparisonBanner({ comparison }) {
  if (!comparison) return null;
  const ready = comparison.status === "COMPARABLE";
  return (
    <div className="mt-4 flex flex-col gap-2 rounded-xl border border-white/10 bg-slate-900/70 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Forward-test comparison</div>
        <div className="mt-1 text-sm font-medium text-white">
          {ready ? `Research leader: ${comparison.research_leader_strategy_id || "calculating"}` : `Collecting ${comparison.minimum_closed_trades_per_strategy || 30} closed shadow trades per strategy`}
        </div>
        <div className="mt-1 text-xs text-slate-500">Current ranking: {(comparison.ranking || []).join(" → ") || "waiting for data"}</div>
      </div>
      <StatusBadge label={comparison.status} tone={ready ? "emerald" : "amber"} />
    </div>
  );
}

function StrategyPanel({ strategy }) {
  const performance = strategy.performance || {};
  const officialPerformance = strategy.official_performance || {};
  const coverage = strategy.coverage || {};
  const readiness = strategy.forward_test_readiness || {};
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
              <StatusBadge label={readiness.status || "COLLECTING"} tone={readiness.status === "COMPARABLE" ? "emerald" : "amber"} />
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
          <Metric label="Shadow trades" value={performance.total_trades || 0} icon={Layers3} />
          <Metric label="Win rate" value={formatPercent(performance.win_rate || 0, 1)} icon={TrendingUp} tone="emerald" />
          <Metric label="Drawdown" value={formatPercent(performance.max_drawdown_percent || 0, 2)} icon={TrendingDown} tone="rose" />
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
          <ValueCard label="Shadow net P&L" value={`₹${number(performance.net_pnl_inr, 2)}`} tone={performance.net_pnl_inr >= 0 ? "emerald" : "rose"} />
          <ValueCard label="Shadow return" value={formatSigned(performance.account_return_percent || 0, 2) + "%"} tone={performance.account_return_percent >= 0 ? "emerald" : "rose"} />
          <ValueCard label="Gross trade P&L" value={formatSigned(performance.gross_trade_pnl_percent || 0, 2) + "%"} />
          <ValueCard label="Fees" value={formatPercent(performance.fees_percent || 0, 2)} tone="amber" />
          <ValueCard label="Funding cost" value={formatPercent(performance.funding_cost_percent || 0, 3)} tone="amber" />
          <ValueCard label="Profit factor" value={performance.profit_factor == null ? "—" : number(performance.profit_factor, 2)} />
          <ValueCard label="Official winner trades" value={officialPerformance.total_trades || 0} tone="cyan" />
        </div>

        <div className="mt-3 text-xs text-slate-500">
          Forward comparison requires {readiness.minimum_closed_trades || 30} closed shadow trades per strategy; {readiness.remaining_trades || 0} remain for this strategy. Comparison never enables live orders automatically.
        </div>
        <div className="mt-1 text-xs text-slate-500">
          Eligible scans are evaluations, not separate positions. Repeated unchanged signals reuse the matching open plan or position; only one official paper winner may be active per coin.
        </div>

        <CandidateTable candidates={strategy.candidates || []} />
      </div>
    </article>
  );
}

function CandidateTable({ candidates }) {
  return (
    <div className="mt-4 overflow-hidden rounded-xl border border-white/10">
      <div className="flex items-center justify-between border-b border-white/10 bg-slate-950/60 px-4 py-3">
        <div className="text-sm font-medium text-white">Latest candidate per coin</div>
        <div className="text-xs text-slate-500">Signal → shadow portfolio → official winner</div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[1080px] w-full text-left text-xs">
          <thead className="bg-slate-950/40 text-[10px] uppercase tracking-[0.14em] text-slate-500">
            <tr><th className="px-4 py-2.5">Coin</th><th>Side / TF</th><th>Score</th><th>Confidence</th><th>Strategy decision</th><th>Market Move</th><th>Shadow</th><th>Official</th><th>Reason</th><th>Evaluated IST</th></tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {candidates.map((candidate) => (
              <tr key={candidate.decision_snapshot_id} className="text-slate-300">
                <td className="px-4 py-3 font-semibold text-white">{candidate.symbol}</td>
                <td>{candidate.side || "—"} · {candidate.timeframe || "—"}</td>
                <td className={numberTone(candidate.score)}>{candidate.score === null || candidate.score === undefined ? "—" : formatSigned(candidate.score, 1)}</td>
                <td>{formatPercent(candidate.confidence || 0, 1)}</td>
                <td><StatusBadge label={candidate.decision} tone={candidate.decision === "ELIGIBLE" ? "emerald" : "rose"} /></td>
                <td><StatusBadge label={candidate.market_participation?.direction || candidate.market_participation?.status || "N/A"} tone={directionTone(candidate.market_participation?.direction)} /></td>
                <td>{candidate.shadow_lifecycle?.replaceAll("_", " ")}</td>
                <td>{candidate.lifecycle?.replaceAll("_", " ")}</td>
                <td className="max-w-[340px] py-3 pr-3 text-slate-400">{candidate.blocked_reasons?.[0] || candidate.market_participation?.reason || "All current strategy gates passed"}</td>
                <td className="pr-4 text-slate-500"><span className="inline-flex items-center gap-1"><Clock3 className="h-3.5 w-3.5" />{formatTimeInIst(candidate.created_at)}</span></td>
              </tr>
            ))}
            {!candidates.length ? <tr><td colSpan="10" className="px-4 py-8 text-center text-slate-500">Waiting for the next strategy scan.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Metric({ label, value, icon: Icon, tone = "cyan" }) {
  return <div className="rounded-lg border border-white/10 bg-slate-950/55 p-3"><div className="flex items-center justify-between text-[10px] uppercase tracking-[0.14em] text-slate-500"><span>{label}</span><Icon className={clsx("h-4 w-4", toneClass(tone))} /></div><div className="mt-2 text-xl font-semibold text-white">{value}</div></div>;
}

function ValueCard({ label, value, tone = "slate" }) {
  return <div className="rounded-lg border border-white/10 bg-slate-950/45 px-3 py-2.5"><div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</div><div className={clsx("mt-1 text-sm font-semibold", toneClass(tone))}>{value}</div></div>;
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
