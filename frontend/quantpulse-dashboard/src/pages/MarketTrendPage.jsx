import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, Database, Gauge, RadioTower, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { loadMarketParticipationTrends } from "../hooks/dashboardApi";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";

export default function MarketTrendPage({ activeSymbol, getSymbolHref }) {
  const [payload, setPayload] = useState({ records: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    loadMarketParticipationTrends({ signal: controller.signal })
      .then(setPayload)
      .catch((requestError) => {
        if (requestError?.name !== "AbortError") setError(requestError?.message || "Market trend is unavailable");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [refreshKey]);

  const records = payload?.records || [];
  const selected = records.find((item) => item.symbol === activeSymbol) || records[0] || null;
  const bullish = records.filter((item) => item.direction === "BULLISH").length;
  const bearish = records.filter((item) => item.direction === "BEARISH").length;
  const neutral = records.length - bullish - bearish;
  const breadth = selected?.breadth || {};
  const timeframeRows = selected?.spot?.timeframes || [];
  const componentRows = useMemo(
    () => Object.entries(selected?.components || {}).map(([name, score]) => ({ name, score: Number(score || 0) })),
    [selected]
  );

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Independent confirmation</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Market participation trend</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-400">
              Genuine Binance spot taker flow, dynamic support/resistance, futures positioning, ETH/BTC, breadth and observed liquidation pressure.
            </p>
          </div>
          <button type="button" onClick={() => setRefreshKey((value) => value + 1)} className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/10 bg-slate-900 px-3 text-sm text-slate-200 hover:border-cyan-400/30">
            <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} /> Refresh
          </button>
        </div>

        {error ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div> : null}

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Bullish" value={bullish} note="Spot-supported LONG context" icon={TrendingUp} accent="emerald" />
          <MetricCard label="Bearish" value={bearish} note="Spot-supported SHORT context" icon={TrendingDown} accent="rose" />
          <MetricCard label="Neutral" value={neutral} note="No execution alignment" icon={Activity} accent="amber" />
          <MetricCard label="Coverage" value={`${records.length}`} note="Tracked market trends" icon={Database} accent="cyan" />
        </div>

        <div className="mt-3.5 grid gap-3 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-white">All symbols</div>
                <div className="text-xs text-slate-500">Separate from the existing regime engine</div>
              </div>
              <Pill tone="cyan">±40 execution</Pill>
            </div>
            <div className="space-y-2">
              {records.map((row) => (
                <Link key={row.symbol} to={getSymbolHref(row.symbol)} className={row.symbol === activeSymbol ? "block rounded-lg border border-cyan-400/35 bg-cyan-500/10 p-3" : "block rounded-lg border border-white/10 bg-slate-950/70 p-3 hover:border-cyan-400/25"}>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-medium text-white">{row.symbol}</div>
                      <div className="mt-1 text-xs text-slate-500">{row.quality_state || row.status}</div>
                    </div>
                    <div className="text-right">
                      <Pill tone={directionTone(row.direction)}>{row.direction || "NEUTRAL"}</Pill>
                      <div className="mt-1 text-xs text-slate-400">{signed(row.score)} · {percent(row.confidence)}</div>
                    </div>
                  </div>
                </Link>
              ))}
              {!records.length && !loading ? <div className="rounded-lg border border-white/10 bg-slate-950/70 p-3 text-sm text-slate-500">Waiting for the first worker calculation.</div> : null}
            </div>
          </div>

          <div className="space-y-3">
            <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Selected trend</div>
                  <div className="mt-1 text-lg font-semibold text-white">{selected?.symbol || activeSymbol}</div>
                </div>
                <Pill tone={directionTone(selected?.direction)}>{selected?.direction || "WAITING"}</Pill>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <MiniStat label="Score" value={signed(selected?.score)} />
                <MiniStat label="Confidence" value={percent(selected?.confidence)} />
                <MiniStat label="Bull breadth" value={percent(breadth?.bullish_percent)} />
                <MiniStat label="Bear breadth" value={percent(breadth?.bearish_percent)} />
              </div>
              <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/70 p-3 text-sm text-slate-300">
                {selected?.direction === "BULLISH" ? "Eligible to confirm LONG signals only." : selected?.direction === "BEARISH" ? "Eligible to confirm SHORT signals only." : "Neutral participation blocks new paper entries."}
              </div>
            </div>

            <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white"><RadioTower className="h-4 w-4 text-cyan-300" />Timeframe spot evidence</div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="text-[11px] uppercase tracking-[0.14em] text-slate-500"><tr><th className="pb-2">Timeframe</th><th className="pb-2">Direction</th><th className="pb-2">Score</th><th className="pb-2">Spot CVD</th><th className="pb-2">Rel volume</th><th className="pb-2">Resistance</th></tr></thead>
                  <tbody className="divide-y divide-white/5">
                    {timeframeRows.map((row) => <tr key={row.timeframe}><td className="py-2 text-white">{row.timeframe}</td><td className="py-2"><Pill tone={directionTone(row.direction)}>{row.direction}</Pill></td><td className="py-2 text-slate-300">{signed(row.score)}</td><td className="py-2 text-slate-300">{signed(row.spot_cvd_percent, 2)}%</td><td className="py-2 text-slate-300">{Number(row.relative_spot_volume || 0).toFixed(2)}x</td><td className="py-2 text-slate-300">{zone(row.resistance)}</td></tr>)}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white"><Gauge className="h-4 w-4 text-cyan-300" />Score components</div>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{componentRows.map((item) => <MiniStat key={item.name} label={item.name.replaceAll("_", " ")} value={signed(item.score)} />)}</div>
              <div className="mt-3 text-xs text-slate-500">ETF, macro, regulatory and corporate-flow context remains advisory and unavailable until a verified provider is connected.</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function MiniStat({ label, value }) {
  return <div className="rounded-lg border border-white/10 bg-slate-950/70 p-2.5"><div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</div><div className="mt-1 font-medium text-white">{value}</div></div>;
}

function directionTone(direction) {
  if (direction === "BULLISH") return "emerald";
  if (direction === "BEARISH") return "rose";
  return "amber";
}

function signed(value, digits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function percent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(0)}%` : "-";
}

function zone(value) {
  if (!value) return "None";
  return `${Number(value.lower).toLocaleString()}–${Number(value.upper).toLocaleString()} (${value.tests} tests)`;
}
