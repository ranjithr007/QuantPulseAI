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
  const normalizedActiveSymbol = String(activeSymbol || "").toUpperCase();
  const selected = records.find((item) => String(item.symbol || "").toUpperCase() === normalizedActiveSymbol) || records[0] || null;
  const bullish = records.filter((item) => item.direction === "BULLISH").length;
  const bearish = records.filter((item) => item.direction === "BEARISH").length;
  const neutral = records.length - bullish - bearish;
  const breadth = selected?.breadth || {};
  const timeframeRows = selected?.spot?.timeframes || [];
  const timeframeSummary = summarizeTimeframeDirections(timeframeRows);
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
                <div className="text-sm font-medium text-white">All symbols — combined trend</div>
                <div className="text-xs text-slate-500">Final direction after weighting all timeframe evidence and confirmation inputs</div>
              </div>
              <Pill tone="cyan">Combined ±40</Pill>
            </div>
            <div className="space-y-2">
              {records.map((row) => (
                <Link key={row.symbol} to={getSymbolHref(row.symbol)} className={String(row.symbol || "").toUpperCase() === normalizedActiveSymbol ? "block rounded-lg border border-cyan-400/35 bg-cyan-500/10 p-3" : "block rounded-lg border border-white/10 bg-slate-950/70 p-3 hover:border-cyan-400/25"}>
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
                  <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Selected combined execution trend</div>
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
                <div>{combinedTrendExplanation(selected, timeframeSummary)}</div>
                <div className="mt-1 text-xs text-slate-500">{timeframeDirectionSummary(timeframeSummary)}</div>
              </div>
            </div>

            <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
              <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-center gap-2 text-sm font-medium text-white"><RadioTower className="h-4 w-4 text-cyan-300" />Per-timeframe spot evidence</div>
                <div className="text-xs text-slate-500">Evidence only: Bullish ≥ +15 · Bearish ≤ −15 · otherwise Neutral</div>
              </div>
              <div className="mt-3 grid gap-3 2xl:grid-cols-2">
                {timeframeRows.map((row) => <TimeframeEvidenceCard key={row.timeframe} row={row} />)}
              </div>
              <div className="mt-3 rounded-md border border-cyan-400/15 bg-cyan-500/5 p-2.5 text-xs text-slate-500">
                These timeframe labels do not override the selected combined trend. The weighted timeframe score plus confirmation inputs must reach +{executionThreshold(selected)} for Bullish or −{executionThreshold(selected)} for Bearish.
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

function TimeframeEvidenceCard({ row }) {
  const components = row?.score_components || {};
  const componentRows = [
    ["EMA", components.ema],
    ["CVD", components.cvd],
    ["Price", components.price_change],
    ["Volume", components.relative_volume],
    ["Resistance", components.resistance],
    ["Support", components.support],
  ];
  const hasComponents = componentRows.some(([, value]) => Number.isFinite(Number(value)));
  const emaPosition = Number(row?.spot_price) > Number(row?.ema20) ? "Above" : Number(row?.spot_price) < Number(row?.ema20) ? "Below" : "At EMA";

  return (
    <article className="rounded-lg border border-white/10 bg-slate-950/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-base font-semibold text-white">{row.timeframe}</span>
          <Pill tone={directionTone(row.direction)}>TF {row.direction || "NEUTRAL"}</Pill>
        </div>
        <div className="text-lg font-semibold text-white">{signed(row.score)}</div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <EvidenceMetric label="Spot CVD" value={`${signed(row.spot_cvd_percent, 2)}%`} tone={numberTone(row.spot_cvd_percent)} />
        <EvidenceMetric label="Price change" value={`${signed(row.price_change_percent, 2)}%`} tone={numberTone(row.price_change_percent)} />
        <EvidenceMetric label="Relative volume" value={`${Number(row.relative_spot_volume || 0).toFixed(2)}x`} />
        <EvidenceMetric label="Price vs EMA20" value={emaPosition} tone={emaPosition === "Above" ? "emerald" : emaPosition === "Below" ? "rose" : "slate"} />
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <ZoneLine label="Support" value={row.support} tone="emerald" />
        <ZoneLine label="Resistance" value={row.resistance} tone="rose" />
      </div>

      <div className="mt-3">
        <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Score contributions</div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {hasComponents
            ? componentRows.map(([label, value]) => <ScoreContribution key={label} label={label} value={value} />)
            : <span className="text-xs text-slate-500">Contribution details will appear after the next worker calculation.</span>}
        </div>
      </div>

      <div className="mt-3 text-xs leading-5 text-slate-400">
        {(row.reasons || []).join(" · ") || row.status || "No evidence reasons available"}
      </div>
    </article>
  );
}

function EvidenceMetric({ label, value, tone = "slate" }) {
  const toneClass = tone === "emerald" ? "text-emerald-300" : tone === "rose" ? "text-rose-300" : "text-slate-200";
  return <div className="rounded-md border border-white/5 bg-slate-900/70 p-2"><div className="text-[9px] uppercase tracking-[0.12em] text-slate-500">{label}</div><div className={`mt-1 text-sm font-medium ${toneClass}`}>{value}</div></div>;
}

function ZoneLine({ label, value, tone }) {
  const toneClass = tone === "emerald" ? "text-emerald-300" : "text-rose-300";
  return <div className="rounded-md border border-white/5 bg-slate-900/70 p-2"><div className={`text-[10px] uppercase tracking-[0.12em] ${toneClass}`}>{label}</div><div className="mt-1 text-xs text-slate-300">{zone(value)}</div></div>;
}

function ScoreContribution({ label, value }) {
  const number = Number(value);
  const toneClass = number > 0 ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200" : number < 0 ? "border-rose-400/20 bg-rose-500/10 text-rose-200" : "border-white/10 bg-slate-900 text-slate-400";
  return <span className={`rounded-md border px-2 py-1 text-[10px] ${toneClass}`}>{label} {signed(number)}</span>;
}

function numberTone(value) {
  const number = Number(value);
  if (number > 0) return "emerald";
  if (number < 0) return "rose";
  return "slate";
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

function executionThreshold(selected) {
  const threshold = Number(selected?.execution_threshold);
  return Number.isFinite(threshold) && threshold > 0 ? threshold.toFixed(0) : "40";
}

function summarizeTimeframeDirections(rows) {
  return (rows || []).reduce(
    (summary, row) => {
      const direction = String(row?.direction || "NEUTRAL").toUpperCase();
      if (direction === "BULLISH") summary.bullish += 1;
      else if (direction === "BEARISH") summary.bearish += 1;
      else summary.neutral += 1;
      summary.total += 1;
      return summary;
    },
    { bullish: 0, bearish: 0, neutral: 0, total: 0 }
  );
}

function timeframeDirectionSummary(summary) {
  if (!summary.total) return "Waiting for per-timeframe evidence.";
  return `Timeframe evidence: ${summary.bullish} bullish · ${summary.bearish} bearish · ${summary.neutral} neutral.`;
}

function combinedTrendExplanation(selected, summary) {
  if (!selected) return "Waiting for the combined market-participation calculation.";
  if (selected.direction === "BULLISH") return "Combined score reached the execution threshold. Eligible to confirm LONG signals only.";
  if (selected.direction === "BEARISH") return "Combined score reached the execution threshold. Eligible to confirm SHORT signals only.";

  const score = Number(selected.score || 0);
  const threshold = executionThreshold(selected);
  const evidence = summary.total ? `${summary.bullish}/${summary.total} bullish timeframes` : "available timeframe evidence";
  const boundary = score >= 0 ? `+${threshold}` : `−${threshold}`;
  return `${evidence}, but the combined score ${signed(score)} has not reached ${boundary}. The combined execution trend therefore remains NEUTRAL and blocks new paper entries.`;
}
