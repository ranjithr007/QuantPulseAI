import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Activity, ArrowRight, Gauge, RadioTower, TrendingDown, TrendingUp } from "lucide-react";
import { enrichRow } from "../components/MarketSignalTable";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { formatSigned, tooltipStyle } from "../utils/formatters";

const QUADRANTS = ["LEADING", "IMPROVING", "WEAKENING", "LAGGING"];
const QUADRANT_TONES = {
  LEADING: "emerald",
  IMPROVING: "cyan",
  WEAKENING: "amber",
  LAGGING: "rose",
  UNAVAILABLE: "slate",
};
const QUADRANT_COLORS = {
  LEADING: "#10b981",
  IMPROVING: "#06b6d4",
  WEAKENING: "#f59e0b",
  LAGGING: "#f43f5e",
};

export default function RotationPage({ signalRows, watchlist, auto, getSymbolHref }) {
  const rows = signalRows.map((row) => enrichRow(row, watchlist, undefined, auto?.minConfidence ?? 40));
  const readyRows = rows.filter((row) => row.rotationStatus === "READY");
  const unavailableRows = rows.filter((row) => row.rotationStatus !== "READY");
  const groups = Object.fromEntries(
    QUADRANTS.map((quadrant) => [quadrant, readyRows.filter((row) => row.rotationQuadrant === quadrant)])
  );
  const chartGroups = Object.fromEntries(
    QUADRANTS.map((quadrant) => [
      quadrant,
      groups[quadrant].map((row) => ({ ...row, rotationStrength: row.rsScore })),
    ])
  );
  const quadrantMix = QUADRANTS.map((quadrant) => ({
    quadrant,
    count: groups[quadrant].length,
  }));
  const state = rotationState(groups, readyRows.length);
  const strongest = [...readyRows].sort((a, b) => (b.rsScore ?? -Infinity) - (a.rsScore ?? -Infinity))[0];
  const fastestImprover = [...readyRows].sort(
    (a, b) => (b.rotationMomentum ?? -Infinity) - (a.rotationMomentum ?? -Infinity)
  )[0];

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Relative Rotation</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Crypto leadership rotation</h2>
            <p className="mt-1 text-xs text-slate-500">Relative-strength level versus short-to-higher-timeframe RS momentum. This is not capital-flow measurement.</p>
          </div>
          <Pill tone={state.tone}>{state.label}</Pill>
        </div>

        {unavailableRows.length ? (
          <div className="mt-3 rounded-lg border border-amber-400/25 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-900">
            <div className="font-medium">Rotation unavailable for {unavailableRows.length} symbol{unavailableRows.length === 1 ? "" : "s"}</div>
            <div className="mt-1 text-xs text-amber-800">
              {unavailableRows.map((row) => `${row.symbol}: ${row.rotationReason}`).join(" · ")}
            </div>
          </div>
        ) : null}

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Rotation state" value={state.label} note={state.note} icon={RadioTower} accent={state.tone} />
          <MetricCard label="RS leader" value={strongest?.symbol || "-"} note={formatSigned(strongest?.rsScore, 0, "-")} icon={TrendingUp} accent="emerald" />
          <MetricCard label="Fastest improver" value={fastestImprover?.symbol || "-"} note={`Momentum ${formatSigned(fastestImprover?.rotationMomentum, 0, "-")}`} icon={Activity} accent="cyan" />
          <MetricCard label="Evidence coverage" value={`${readyRows.length}/${rows.length}`} note="Complete four-timeframe RS" icon={Gauge} accent={unavailableRows.length ? "amber" : "cyan"} />
        </div>

        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Leading" value={groups.LEADING.length} note="Strong and improving" icon={TrendingUp} accent="emerald" compact />
          <MetricCard label="Improving" value={groups.IMPROVING.length} note="Weak but gaining" icon={Activity} accent="cyan" compact />
          <MetricCard label="Weakening" value={groups.WEAKENING.length} note="Strong but fading" icon={Gauge} accent="amber" compact />
          <MetricCard label="Lagging" value={groups.LAGGING.length} note="Weak and declining" icon={TrendingDown} accent="rose" compact />
        </div>

        <div className="mt-3.5 grid gap-3.5 xl:grid-cols-[0.65fr_1.35fr]">
          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3">
              <div className="text-sm font-medium text-white">Quadrant distribution</div>
              <div className="text-xs text-slate-500">Current leadership phase across the tracked universe</div>
            </div>
            <div className="h-80 min-h-0 min-w-0">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 420, height: 320 }}>
                <PieChart>
                  <Pie data={quadrantMix} dataKey="count" nameKey="quadrant" innerRadius={58} outerRadius={92}>
                    {QUADRANTS.map((quadrant) => <Cell key={quadrant} fill={QUADRANT_COLORS[quadrant]} />)}
                  </Pie>
                  <Tooltip contentStyle={tooltipStyle()} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3">
              <div className="text-sm font-medium text-white">Relative rotation map</div>
              <div className="text-xs text-slate-500">Right is stronger RS; up is improving lower-timeframe momentum</div>
            </div>
            <div className="h-80 min-h-0 min-w-0">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 720, height: 320 }}>
                <ScatterChart margin={{ top: 12, right: 20, bottom: 16, left: 4 }}>
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" />
                  <XAxis type="number" dataKey="rotationStrength" name="RS" domain={[-110, 110]} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <YAxis type="number" dataKey="rotationMomentum" name="Momentum" domain={[-110, 110]} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <ZAxis type="number" dataKey="confidence" name="Signal confidence" range={[70, 220]} />
                  <ReferenceLine x={0} stroke="#94a3b8" strokeDasharray="4 4" />
                  <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="4 4" />
                  <Tooltip cursor={{ strokeDasharray: "4 4" }} contentStyle={tooltipStyle()} content={<RotationTooltip />} />
                  {QUADRANTS.map((quadrant) => (
                    <Scatter key={quadrant} name={quadrant} data={chartGroups[quadrant]} fill={QUADRANT_COLORS[quadrant]} />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="mt-3.5 grid gap-3 xl:grid-cols-4">
          {QUADRANTS.map((quadrant) => (
            <RotationGroup key={quadrant} quadrant={quadrant} rows={groups[quadrant]} getSymbolHref={getSymbolHref} />
          ))}
        </div>
      </div>
    </section>
  );
}

function RotationGroup({ quadrant, rows, getSymbolHref }) {
  const sorted = [...rows].sort((a, b) => (b.rsScore ?? -Infinity) - (a.rsScore ?? -Infinity));
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{quadrantLabel(quadrant)}</div>
          <div className="text-xs text-slate-500">{quadrantDescription(quadrant)}</div>
        </div>
        <Pill tone={QUADRANT_TONES[quadrant]}>{rows.length}</Pill>
      </div>
      <div className="space-y-2">
        {sorted.map((row) => (
          <Link key={row.symbol} to={getSymbolHref(row.symbol)} className="block rounded-lg border border-white/10 bg-slate-950/70 p-2.5 transition hover:border-cyan-400/30">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-white">{row.symbol}</span>
              <Pill tone={row.type === "BUY" ? "emerald" : row.type === "SELL" ? "rose" : "slate"}>{row.type}</Pill>
            </div>
            <div className="mt-1.5 grid grid-cols-2 gap-2 text-[11px] text-slate-400">
              <span>RS {formatSigned(row.rsScore, 0, "-")}</span>
              <span>Momentum {formatSigned(row.rotationMomentum, 0, "-")}</span>
            </div>
            <div className="mt-1.5 line-clamp-2 text-[11px] leading-4 text-slate-500">{row.rotationReason}</div>
            <div className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-cyan-700">Details <ArrowRight className="h-3.5 w-3.5" /></div>
          </Link>
        ))}
        {!sorted.length ? <div className="rounded-lg border border-white/10 bg-slate-950/70 p-3 text-sm text-slate-500">No symbols in this quadrant.</div> : null}
      </div>
    </div>
  );
}

function RotationTooltip({ active, payload }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-2.5 text-xs shadow-lg">
      <div className="font-semibold text-slate-900">{row.symbol}</div>
      <div className="mt-1 text-slate-600">{row.rotationQuadrant}</div>
      <div className="text-slate-600">RS {formatSigned(row.rsScore, 1, "-")}</div>
      <div className="text-slate-600">Momentum {formatSigned(row.rotationMomentum, 1, "-")}</div>
    </div>
  );
}

function rotationState(groups, total) {
  if (!total) return { label: "Unavailable", note: "No complete RS evidence", tone: "slate" };
  const broadening = groups.LEADING.length + groups.IMPROVING.length;
  const fading = groups.WEAKENING.length + groups.LAGGING.length;
  if (broadening > fading) return { label: "Leadership broadening", note: `${broadening} symbols leading or improving`, tone: "emerald" };
  if (fading > broadening) return { label: "Leadership fading", note: `${fading} symbols weakening or lagging`, tone: "rose" };
  return { label: "Balanced rotation", note: "Leadership and weakness are evenly distributed", tone: "cyan" };
}

function quadrantLabel(quadrant) {
  return quadrant.charAt(0) + quadrant.slice(1).toLowerCase();
}

function quadrantDescription(quadrant) {
  return {
    LEADING: "Positive RS, improving momentum",
    IMPROVING: "Negative RS, improving momentum",
    WEAKENING: "Positive RS, fading momentum",
    LAGGING: "Negative RS, fading momentum",
  }[quadrant];
}
