import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { enrichRow } from "../components/MarketSignalTable";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { Activity, ArrowRight, Gauge, RadioTower, TrendingDown, TrendingUp } from "lucide-react";
import { formatPercent, tooltipStyle } from "../utils/formatters";

const COLORS = ["#34d399", "#fb7185", "#94a3b8"];

export default function RotationPage({ signalRows, watchlist, auto, getSymbolHref }) {
  const rows = signalRows.map((row) => enrichRow(row, watchlist, undefined, auto?.minConfidence ?? 40));
  const longRows = rows.filter((row) => row.type === "BUY");
  const shortRows = rows.filter((row) => row.type === "SELL");
  const waitRows = rows.filter((row) => row.type === "WAIT");
  const rotation = rotationState(longRows, shortRows, waitRows);
  const leadership = [...rows].sort((a, b) => b.confidence - a.confidence).slice(0, 6);
  const leaders = longRows.slice().sort((a, b) => b.confidence - a.confidence).slice(0, 3);
  const laggards = shortRows.slice().sort((a, b) => b.confidence - a.confidence).slice(0, 3);
  const longAvg = average(longRows.map((row) => row.confidence));
  const shortAvg = average(shortRows.map((row) => row.confidence));
  const rotationSpread = longAvg - shortAvg;

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Rotation</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Crypto rotation map</h2>
          </div>
          <Pill tone={rotation.tone}>{rotation.label}</Pill>
        </div>

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Rotation state" value={rotation.label} note={rotation.note} icon={RadioTower} accent={rotation.tone} />
          <MetricCard label="Long leaders" value={longRows.length} note="AI BUY symbols" icon={TrendingUp} accent="emerald" />
          <MetricCard label="Short leaders" value={shortRows.length} note="AI SELL symbols" icon={TrendingDown} accent="rose" />
          <MetricCard label="Confidence spread" value={formatPercent(rotationSpread, 0)} note="Avg BUY minus SELL confidence" icon={Gauge} accent={rotationSpread >= 0 ? "emerald" : "rose"} />
        </div>

        <div className="mt-3 grid gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
          <MetricCard label="BUY breadth" value={longRows.length} note={`${formatPercent((longRows.length / Math.max(rows.length, 1)) * 100, 0)} of universe`} icon={TrendingUp} accent="emerald" compact />
          <MetricCard label="SELL breadth" value={shortRows.length} note={`${formatPercent((shortRows.length / Math.max(rows.length, 1)) * 100, 0)} of universe`} icon={TrendingDown} accent="rose" compact />
          <MetricCard label="WAIT breadth" value={waitRows.length} note={`${formatPercent((waitRows.length / Math.max(rows.length, 1)) * 100, 0)} of universe`} icon={Activity} accent="amber" compact />
          <MetricCard label="BUY avg confidence" value={formatPercent(longAvg, 0, "-")} note="BUY subset average" icon={Gauge} accent="emerald" compact />
          <MetricCard label="SELL avg confidence" value={formatPercent(shortAvg, 0, "-")} note="SELL subset average" icon={Gauge} accent="rose" compact />
          <MetricCard label="Universe" value={rows.length} note="Tracked symbols" icon={RadioTower} accent="cyan" compact />
        </div>

        <div className="mt-3.5 grid gap-3.5 xl:grid-cols-[0.65fr_1.35fr]">
          <ChartCard title="Signal breadth" subtitle="BUY / SELL / WAIT distribution">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={[
                    { name: "BUY", value: longRows.length },
                    { name: "SELL", value: shortRows.length },
                    { name: "WAIT", value: waitRows.length },
                  ]}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={56}
                  outerRadius={88}
                >
                  {COLORS.map((color) => (
                    <Cell key={color} fill={color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={tooltipStyle()} />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Directional confidence" subtitle="Strongest signal confidence by symbol">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={leadership}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="symbol" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatPercent(value, 0), "Confidence"]} />
                <Bar dataKey="confidence" radius={[6, 6, 0, 0]}>
                  {leadership.map((row) => (
                    <Cell key={row.symbol} fill={row.type === "BUY" ? "#34d399" : row.type === "SELL" ? "#fb7185" : "#94a3b8"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <div className="mt-3.5 grid gap-3 xl:grid-cols-2">
          <LeadList title="Top long leaders" rows={leaders} tone="emerald" getSymbolHref={getSymbolHref} />
          <LeadList title="Top short leaders" rows={laggards} tone="rose" getSymbolHref={getSymbolHref} />
        </div>

        <div className="mt-3.5 grid gap-3 xl:grid-cols-3">
          {leadership.map((row) => (
            <RotationCard key={row.symbol} row={row} href={getSymbolHref(row.symbol)} />
          ))}
        </div>
      </div>
    </section>
  );
}

function RotationCard({ row, href }) {
  return (
    <Link to={href} className="rounded-lg border border-white/10 bg-slate-900/70 p-3 transition hover:border-cyan-400/35 hover:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-base font-semibold text-white sm:text-lg">{row.symbol}</div>
          <div className="mt-1 text-[11px] uppercase tracking-[0.16em] text-slate-500">{row.stage}</div>
        </div>
        <Pill tone={row.type === "BUY" ? "emerald" : row.type === "SELL" ? "rose" : "slate"}>{row.type}</Pill>
      </div>
      <div className="mt-2.5 grid grid-cols-2 gap-2.5 text-sm">
        <MiniStat label="Confidence" value={formatPercent(row.confidence, 0)} />
        <MiniStat label="Risk" value={row.riskLabel} />
      </div>
      <div className="mt-2.5">
        <Pill tone={row.riskTone}>{row.riskLabel}</Pill>
        {row.riskNote ? <div className="mt-1 text-[11px] leading-4 text-slate-500">{row.riskNote}</div> : null}
      </div>
      <div className="mt-2.5 flex items-center gap-2 text-sm font-medium text-cyan-200">
        View Details
        <ArrowRight className="h-4 w-4" />
      </div>
    </Link>
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

function MiniStat({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 p-3">
      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 font-medium text-white">{value}</div>
    </div>
  );
}

function LeadList({ title, rows, tone, getSymbolHref }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{title}</div>
          <div className="text-xs text-slate-500">Highest signal strength in this direction</div>
        </div>
        <Pill tone={tone}>{rows.length} shown</Pill>
      </div>
      <div className="space-y-2">
        {rows.map((row, index) => (
          <Link
            key={row.symbol}
            to={getSymbolHref(row.symbol)}
            className="flex items-center justify-between rounded-lg border border-white/10 bg-slate-950/70 px-3 py-2 transition hover:border-cyan-400/30 hover:bg-slate-900"
          >
            <div className="min-w-0">
              <div className="text-sm font-medium text-white">{row.symbol}</div>
              <div className="text-[11px] text-slate-500">#{index + 1} {row.stage}</div>
              {row.riskNote ? <div className="mt-1 text-[11px] text-slate-500">{row.riskNote}</div> : null}
            </div>
            <div className="text-right">
              <div className="text-sm font-semibold text-white">{formatPercent(row.confidence, 0)}</div>
              <div className="text-[11px] text-slate-400">{row.riskLabel}</div>
            </div>
          </Link>
        ))}
        {!rows.length ? <div className="rounded-lg border border-white/10 bg-slate-950/70 p-3 text-sm text-slate-500">No signals in this bucket.</div> : null}
      </div>
    </div>
  );
}

function rotationState(longRows, shortRows, waitRows) {
  if (longRows.length > shortRows.length) return { label: "Risk-on rotation", note: `${longRows.length} long leaders`, tone: "emerald" };
  if (shortRows.length > longRows.length) return { label: "Risk-off rotation", note: `${shortRows.length} short leaders`, tone: "rose" };
  if (waitRows.length > longRows.length + shortRows.length) return { label: "Defensive rotation", note: "Most symbols are WAIT", tone: "amber" };
  return { label: "Balanced rotation", note: "No dominant direction", tone: "cyan" };
}

function average(values) {
  return values.length ? values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length : 0;
}
