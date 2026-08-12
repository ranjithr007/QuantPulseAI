import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Eye, Layers3, ScanLine, TrendingDown, TrendingUp } from "lucide-react";
import { enrichRow } from "../components/MarketSignalTable";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { formatPercent, formatSigned, tooltipStyle } from "../utils/formatters";

const STAGE_ORDER = ["Stage 1 Base", "Stage 2 Uptrend", "Stage 3 Transition", "Stage 4 Downtrend"];
const STAGE_COLORS = {
  "Stage 1 Base": "#22d3ee",
  "Stage 2 Uptrend": "#34d399",
  "Stage 3 Transition": "#f59e0b",
  "Stage 4 Downtrend": "#fb7185",
};

export default function StageAnalysisPage({ signalRows, watchlist, activeSymbol, auto, getSymbolHref }) {
  const rows = signalRows.map((row) => enrichRow(row, watchlist, undefined, auto?.minConfidence ?? 60));
  const groups = STAGE_ORDER.map((stage) => ({
    stage,
    count: rows.filter((row) => row.stage === stage).length,
    avgRs: average(rows.filter((row) => row.stage === stage).map((row) => row.rsScore)),
  }));
  const dominant = [...groups].sort((a, b) => b.count - a.count)[0];
  const uptrend = groups.find((group) => group.stage === "Stage 2 Uptrend");
  const downtrend = groups.find((group) => group.stage === "Stage 4 Downtrend");
  const stageSpread = (uptrend?.avgRs || 0) - (downtrend?.avgRs || 0);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Stage Analysis</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Market stage analysis</h2>
          </div>
          <Pill tone={stageTone(dominant.stage)}>{dominant.stage}</Pill>
        </div>

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Dominant stage" value={dominant.stage} note={`${dominant.count} symbols`} icon={Layers3} accent={stageTone(dominant.stage)} />
          <MetricCard label="Uptrend count" value={uptrend?.count || 0} note="Stage 2 Uptrend" icon={TrendingUp} accent="emerald" />
          <MetricCard label="Downtrend count" value={downtrend?.count || 0} note="Stage 4 Downtrend" icon={TrendingDown} accent="rose" />
          <MetricCard label="Universe" value={rows.length} note="Tracked symbols" icon={ScanLine} accent="cyan" />
        </div>

        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Stage 2 avg RS" value={formatSigned(uptrend?.avgRs || 0, 0, "-")} note="Trend leaders" icon={TrendingUp} accent="emerald" compact />
          <MetricCard label="Stage 4 avg RS" value={formatSigned(downtrend?.avgRs || 0, 0, "-")} note="Trend laggards" icon={TrendingDown} accent="rose" compact />
          <MetricCard label="Stage spread" value={formatSigned(stageSpread, 0, "-")} note="Uptrend minus downtrend" icon={Layers3} accent={stageSpread >= 0 ? "emerald" : "rose"} compact />
          <MetricCard label="Stage base count" value={groups.find((group) => group.stage === "Stage 1 Base")?.count || 0} note="Stage 1 Base" icon={ScanLine} accent="cyan" compact />
        </div>

        <div className="mt-3.5 grid gap-3.5 xl:grid-cols-[0.7fr_1.3fr]">
          <ChartCard title="Stage mix" subtitle="Distribution by stage">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={groups} dataKey="count" nameKey="stage" innerRadius={56} outerRadius={88}>
                  {groups.map((group) => (
                    <Cell key={group.stage} fill={STAGE_COLORS[group.stage]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={tooltipStyle()} />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Average RS by stage" subtitle="Stage quality proxy">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={groups}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="stage" tickLine={false} axisLine={false} tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value, 0), "Avg RS"]} />
                <Bar dataKey="avgRs" radius={[6, 6, 0, 0]}>
                  {groups.map((group) => (
                    <Cell key={group.stage} fill={STAGE_COLORS[group.stage]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <div className="mt-3.5 grid gap-3 xl:grid-cols-4">
          {STAGE_ORDER.map((stage) => (
            <StageColumn
              key={stage}
              stage={stage}
              rows={rows.filter((row) => row.stage === stage)}
              activeSymbol={activeSymbol}
              getSymbolHref={getSymbolHref}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function StageColumn({ stage, rows, activeSymbol, getSymbolHref }) {
  const sortedRows = [...rows].sort((a, b) => b.rsScore - a.rsScore);
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{stage}</div>
          <div className="text-[11px] text-slate-500">{rows.length} symbols</div>
        </div>
        <Pill tone={stageTone(stage)}>{formatSigned(average(rows.map((row) => row.rsScore)), 0, "-")}</Pill>
      </div>
      <div className="space-y-2">
        {sortedRows.map((row) => (
          <Link
            key={row.symbol}
            to={getSymbolHref(row.symbol)}
            className={activeSymbol === row.symbol ? "block rounded-lg border border-cyan-400/35 bg-cyan-500/10 p-2.5" : "block rounded-lg border border-white/10 bg-slate-950/70 p-2.5 transition hover:border-cyan-400/30"}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-white">{row.symbol}</span>
              <Pill tone={row.type === "BUY" ? "emerald" : row.type === "SELL" ? "rose" : "slate"}>{row.type}</Pill>
            </div>
            <div className="mt-1.5 flex items-center justify-between text-[11px] text-slate-400">
              <span>RS {formatSigned(row.rsScore, 0)}</span>
              <span>{formatPercent(row.confidence, 0)}</span>
            </div>
            <div className="mt-1.5">
              <Pill tone={row.riskTone}>{row.riskLabel}</Pill>
              {row.riskNote ? <div className="mt-1 text-[11px] leading-4 text-slate-500">{row.riskNote}</div> : null}
            </div>
            <div className="mt-2.5 inline-flex items-center gap-2 text-xs font-medium text-cyan-200">
              <Eye className="h-3.5 w-3.5" />
              Details
            </div>
          </Link>
        ))}
        {!sortedRows.length ? <div className="rounded-lg border border-white/10 bg-slate-950/70 p-3 text-sm text-slate-500">No symbols in this stage.</div> : null}
      </div>
    </div>
  );
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3">
        <div className="text-sm font-medium text-white">{title}</div>
        <div className="text-xs text-slate-500">{subtitle}</div>
      </div>
      <div className="h-60">{children}</div>
    </div>
  );
}

function stageTone(stage) {
  if (stage === "Stage 2 Uptrend") return "emerald";
  if (stage === "Stage 4 Downtrend") return "rose";
  if (stage === "Stage 3 Transition") return "amber";
  return "cyan";
}

function average(values) {
  return values.length ? values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length : 0;
}
