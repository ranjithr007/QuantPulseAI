import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Award, Eye, Gauge, ShieldCheck, TrendingUp } from "lucide-react";
import { enrichRow } from "../components/MarketSignalTable";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { formatPercent, formatPrice, formatSigned, tooltipStyle } from "../utils/formatters";

export default function RsRankingPage({ signalRows, watchlist, activeSymbol, auto, getSymbolHref }) {
  const rows = signalRows.map((row) => enrichRow(row, watchlist, undefined, auto?.minConfidence ?? 40));
  const rankedRows = rows
    .filter((row) => row.rsStatus === "READY" && row.rsScore !== null)
    .sort((a, b) => b.rsScore - a.rsScore);
  const unavailableRows = rows.filter((row) => row.rsStatus !== "READY" || row.rsScore === null);
  const leader = rankedRows[0];
  const laggard = rankedRows[rankedRows.length - 1];
  const positiveCount = rankedRows.filter((row) => row.rsScore >= 0).length;
  const averageConfidence = rankedRows.length ? rankedRows.reduce((sum, row) => sum + Number(row.confidence || 0), 0) / rankedRows.length : 0;
  const topLeaders = rankedRows.slice(0, 4);
  const bottomLeaders = [...rankedRows].slice(-4).reverse();

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">RS Ranking</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Relative strength ranking</h2>
          </div>
          <Pill tone={unavailableRows.length ? "amber" : "cyan"}>{rankedRows.length}/{rows.length} ranked</Pill>
        </div>

        {unavailableRows.length ? (
          <div className="mt-3 rounded-lg border border-amber-400/25 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-900">
            <div className="font-medium">Relative-strength evidence unavailable for {unavailableRows.length} symbol{unavailableRows.length === 1 ? "" : "s"}</div>
            <div className="mt-1 text-xs text-amber-800">
              {unavailableRows.map((row) => `${row.symbol}: ${row.rsReason}`).join(" · ")}
            </div>
          </div>
        ) : null}

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="RS leader" value={leader?.symbol || "-"} note={formatSigned(leader?.rsScore, 0, "-")} icon={Award} accent="emerald" />
          <MetricCard label="RS laggard" value={laggard?.symbol || "-"} note={formatSigned(laggard?.rsScore, 0, "-")} icon={Gauge} accent="rose" />
          <MetricCard label="Positive RS" value={positiveCount} note={`${rankedRows.length} ranked`} icon={TrendingUp} accent="cyan" />
          <MetricCard label="Eligible" value={rankedRows.filter((row) => row.riskLabel === "Eligible" || row.riskLabel === "Ready to execute").length} note="Risk gate" icon={ShieldCheck} accent="emerald" />
        </div>

        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Average RS" value={formatSigned(average(rankedRows.map((row) => row.rsScore)), 0)} note="Universe mean" icon={Gauge} accent="cyan" compact />
          <MetricCard label="Average confidence" value={formatPercent(averageConfidence, 0)} note="Across ranked universe" icon={TrendingUp} accent="emerald" compact />
          <MetricCard label="Top leaders" value={topLeaders.length} note="Shown below" icon={Award} accent="amber" compact />
          <MetricCard label="Bottom laggards" value={bottomLeaders.length} note="Shown below" icon={ShieldCheck} accent="rose" compact />
        </div>

        <div className="mt-3.5 grid gap-3 xl:grid-cols-2">
          <RankStrip title="Top RS leaders" rows={topLeaders} tone="emerald" getSymbolHref={getSymbolHref} />
          <RankStrip title="Bottom RS laggards" rows={bottomLeaders} tone="rose" getSymbolHref={getSymbolHref} />
        </div>

        <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
          <div className="mb-3">
            <div className="text-sm font-medium text-white">RS score distribution</div>
            <div className="text-xs text-slate-500">Peer percentile of 20-bar returns across 1h / 2h / 4h / 1d; higher timeframes carry more weight</div>
          </div>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rankedRows}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="symbol" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value, 0), "RS"]} />
                <Bar dataKey="rsScore" radius={[6, 6, 0, 0]}>
                  {rankedRows.map((row) => (
                    <Cell key={row.symbol} fill={row.rsScore >= 0 ? "#34d399" : "#fb7185"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="mt-3.5 overflow-hidden rounded-lg border border-white/10 bg-slate-900/70">
          <div className="border-b border-white/10 px-3.5 py-2.5">
            <div className="text-sm font-medium text-white">Ranking table</div>
            <div className="text-xs text-slate-500">Cross-sectional price strength is separate from signal confidence and execution eligibility</div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[960px] divide-y divide-white/5 text-left text-sm">
              <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                <tr>
                  <th className="px-3 py-2.5">Rank</th>
                  <th className="px-3 py-2.5">Symbol</th>
                  <th className="px-3 py-2.5">RS score</th>
                  <th className="px-3 py-2.5">Signal</th>
                  <th className="px-3 py-2.5">Confidence</th>
                  <th className="px-3 py-2.5">Stage</th>
                  <th className="px-3 py-2.5">Price</th>
                  <th className="px-3 py-2.5">Risk</th>
                  <th className="px-3 py-2.5">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {rankedRows.map((row, index) => (
                  <tr key={row.symbol} className={activeSymbol === row.symbol ? "bg-cyan-500/10" : "hover:bg-white/5"}>
                    <td className="px-3 py-2.5 text-slate-400">#{index + 1}</td>
                    <td className="px-3 py-2.5 font-medium text-white">{row.symbol}</td>
                    <td className={row.rsScore >= 0 ? "px-3 py-2.5 font-medium text-emerald-300" : "px-3 py-2.5 font-medium text-rose-300"}>
                      {formatSigned(row.rsScore, 0)} <span className="text-[11px] font-normal text-slate-500">rank #{row.rsRank}/{row.rsUniverseSize}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <Pill tone={row.type === "BUY" ? "emerald" : row.type === "SELL" ? "rose" : "slate"}>{row.type}</Pill>
                    </td>
                    <td className="px-3 py-2.5 text-slate-300">{formatPercent(row.confidence, 0)}</td>
                    <td className="px-3 py-2.5 text-slate-300">{row.stage}</td>
                    <td className="px-3 py-2.5 text-slate-300">{formatPrice(row.currentPrice, { fallback: "-", compactSmall: true })}</td>
                    <td className="px-3 py-2.5">
                      <Pill tone={row.riskTone}>{row.riskLabel}</Pill>
                      {row.riskNote ? <div className="mt-1 max-w-[11rem] text-[11px] leading-4 text-slate-500">{row.riskNote}</div> : null}
                    </td>
                    <td className="px-3 py-2.5">
                      <Link to={getSymbolHref(row.symbol)} className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-slate-950/70 px-2.5 py-1.5 text-xs font-medium text-cyan-200 transition hover:border-cyan-400/40 hover:bg-cyan-500/10">
                        <Eye className="h-3.5 w-3.5" />
                        Details
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}

function RankStrip({ title, rows, tone, getSymbolHref }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{title}</div>
          <div className="text-xs text-slate-500">Fast read on relative strength extremes</div>
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
              <div className="text-[11px] text-slate-500">
                #{index + 1} {row.stage}
              </div>
            </div>
            <div className="text-right">
              <div className={row.rsScore >= 0 ? "text-sm font-semibold text-emerald-300" : "text-sm font-semibold text-rose-300"}>
                {formatSigned(row.rsScore, 0)}
              </div>
              <div className="text-[11px] text-slate-400">{formatPercent(row.confidence, 0)}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function average(values) {
  return values.length ? values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length : 0;
}
