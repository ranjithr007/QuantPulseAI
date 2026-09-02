import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  Activity,
  BarChart3,
  CalendarDays,
  Compass,
  Gauge,
  Newspaper,
  RefreshCw,
  ShieldCheck,
  Target,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import { loadMarketParticipationTrends } from "../hooks/dashboardApi";
import { formatNumber, formatPercent, formatPrice, formatSigned } from "../utils/formatters";
import { buildMoveAnalysis } from "./MarketMovePage";


export default function CoinPulsePage({ view, selectedDetail }) {
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
        if (requestError?.name !== "AbortError") {
          setError(requestError?.message || "Coin Pulse evidence is unavailable");
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [refreshKey]);

  const participation = (payload?.records || []).find(
    (record) => String(record?.symbol || "").toUpperCase() === String(view.symbol || "").toUpperCase()
  ) || null;
  const pulse = useMemo(
    () => buildCoinPulse(view, selectedDetail, participation),
    [view, selectedDetail, participation]
  );

  return (
    <section className="border-b border-slate-200 bg-slate-50/70">
      <div className="mx-auto w-full max-w-[1240px] px-4 py-5 sm:px-6 lg:px-8">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-sky-700">Coin intelligence briefing</div>
            <h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-950">Coin Pulse</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-600">
              A concise evidence report for the selected coin. Change the global symbol, timeframe, or mode to regenerate the briefing.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setRefreshKey((value) => value + 1)}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm transition hover:border-sky-300 hover:text-sky-800"
          >
            <RefreshCw className={clsx("h-4 w-4", loading && "animate-spin")} /> Refresh pulse
          </button>
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</div>
        ) : null}

        <article className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_18px_45px_rgba(15,23,42,0.08)]">
          <PulseMasthead pulse={pulse} loading={loading} />
          <div className="space-y-7 p-5 sm:p-7 lg:p-9">
            <HeadlineMetrics pulse={pulse} />
            <ReportSection icon={Compass} title="What matters now">
              <EvidenceTable rows={pulse.whatMatters} />
            </ReportSection>
            <div className="grid gap-7 lg:grid-cols-[1.1fr_0.9fr]">
              <ReportSection icon={Gauge} title="Engine positioning">
                <EnginePositioning engines={pulse.engines} />
              </ReportSection>
              <ReportSection icon={Target} title="Scenario probability">
                <ProbabilityRows probabilities={pulse.probabilities} />
              </ReportSection>
            </div>
            <ReportSection icon={Zap} title="Primary drivers">
              <DriverGrid drivers={pulse.drivers} />
            </ReportSection>
            <ReportSection icon={Newspaper} title="Market intelligence">
              <p className="text-sm leading-7 text-slate-700">{pulse.narrative}</p>
            </ReportSection>
            <ReportSection icon={Target} title={`Key levels for ${pulse.symbol}`}>
              <KeyLevelGrid pulse={pulse} />
            </ReportSection>
            <div className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-600 sm:flex-row sm:items-center sm:justify-between">
              <span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-600" />Evidence quality: <strong className="text-slate-800">{pulse.quality}</strong></span>
              <span>Decision support only · Paper-trading environment · No live order authorization</span>
            </div>
          </div>
        </article>
      </div>
    </section>
  );
}


function PulseMasthead({ pulse, loading }) {
  const DirectionIcon = pulse.score > 0 ? TrendingUp : pulse.score < 0 ? TrendingDown : Activity;
  return (
    <header className="border-b border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-sky-950 px-5 py-6 text-white sm:px-7 lg:px-9">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.2em] text-sky-200">
            <Newspaper className="h-4 w-4" /> Crypto Daily Pulse
          </div>
          <div className="mt-2 flex items-center gap-2 text-sm text-slate-300">
            <CalendarDays className="h-4 w-4" /> {pulse.reportDate}
          </div>
          <h1 className="mt-5 max-w-3xl text-2xl font-semibold tracking-tight sm:text-3xl">
            {loading && !pulse.hasEvidence ? `Building ${pulse.symbol} briefing…` : pulse.headline}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className={clsx("rounded-full border px-3 py-1 text-xs font-semibold", scoreBadge(pulse.score))}>
              <DirectionIcon className="mr-1 inline h-3.5 w-3.5" /> {pulse.bias}
            </span>
            <span className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-slate-300">
              {pulse.timeframe} · {pulse.mode}
            </span>
          </div>
        </div>
        <div className="min-w-[190px] rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur">
          <div className="text-xs uppercase tracking-[0.16em] text-slate-400">{pulse.symbol}</div>
          <div className="mt-1 text-2xl font-semibold">{pulse.price}</div>
          <div className={clsx("mt-1 text-sm font-medium", numberClass(pulse.change24h))}>
            24H {pulse.change24h === null ? "N/A" : `${formatSigned(pulse.change24h, 2)}%`}
          </div>
        </div>
      </div>
    </header>
  );
}


function HeadlineMetrics({ pulse }) {
  const items = [
    { label: "Bias", value: pulse.bias, note: `Composite ${formatSigned(pulse.score, 0)}`, icon: Compass },
    { label: "Signal confidence", value: formatPercent(pulse.confidence, 1), note: pulse.signalType, icon: Gauge },
    { label: "Funding rate", value: pulse.funding.display, note: pulse.funding.note, icon: BarChart3 },
    { label: "Open interest", value: pulse.openInterest.display, note: pulse.openInterest.note, icon: Activity },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div key={item.label} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.14em] text-slate-500">
              <span>{item.label}</span><Icon className="h-4 w-4 text-sky-600" />
            </div>
            <div className="mt-2 text-lg font-semibold text-slate-950">{item.value}</div>
            <div className="mt-1 text-xs text-slate-500">{item.note}</div>
          </div>
        );
      })}
    </div>
  );
}


function ReportSection({ icon: Icon, title, children }) {
  return (
    <section>
      <h3 className="flex items-center gap-2 border-b border-slate-200 pb-2 text-base font-semibold text-slate-950">
        <Icon className="h-4 w-4 text-sky-700" /> {title}
      </h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}


function EvidenceTable({ rows }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      {rows.map((row, index) => (
        <div key={row.label} className={clsx("grid gap-1 px-4 py-3 text-sm sm:grid-cols-[220px_1fr]", index && "border-t border-slate-200")}>
          <div className="font-medium text-slate-600">{row.label}</div>
          <div className="font-semibold text-slate-950">{row.value}</div>
        </div>
      ))}
    </div>
  );
}


function EnginePositioning({ engines }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-[11px] uppercase tracking-[0.12em] text-slate-500">
          <tr><th className="px-3 py-2.5">Engine</th><th>Score</th><th>Position</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-200">
          {engines.map((engine) => (
            <tr key={engine.label}>
              <td className="px-3 py-3"><div className="font-medium text-slate-900">{engine.label}</div><div className="mt-0.5 max-w-[360px] text-xs text-slate-500">{engine.reason}</div></td>
              <td className={clsx("font-semibold", numberClass(engine.score))}>{engine.score === null ? "N/A" : formatSigned(engine.score, 0)}</td>
              <td className="pr-3 text-xs font-semibold text-slate-700">{enginePosition(engine.score)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function ProbabilityRows({ probabilities }) {
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 p-4">
      {[
        ["Continuation", probabilities.continuation, "bg-emerald-500"],
        ["Pullback", probabilities.pullback, "bg-amber-500"],
        ["Reversal", probabilities.reversal, "bg-rose-500"],
      ].map(([label, value, color]) => (
        <div key={label}>
          <div className="flex items-center justify-between text-sm"><span className="text-slate-600">{label}</span><strong className="text-slate-950">{formatPercent(value, 0)}</strong></div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100"><div className={clsx("h-full rounded-full", color)} style={{ width: `${value}%` }} /></div>
        </div>
      ))}
    </div>
  );
}


function DriverGrid({ drivers }) {
  if (!drivers.length) return <div className="text-sm text-slate-500">Waiting for verified directional evidence.</div>;
  return (
    <ol className="grid gap-2 sm:grid-cols-2">
      {drivers.map((driver, index) => (
        <li key={`${driver}-${index}`} className="flex gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
          <span className="font-semibold text-sky-700">{index + 1}.</span><span>{driver}</span>
        </li>
      ))}
    </ol>
  );
}


function KeyLevelGrid({ pulse }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <LevelCard label="Current price" value={pulse.price} tone="sky" />
      <LevelCard label="Resistance" value={pulse.resistance} tone="rose" />
      <LevelCard label="Support" value={pulse.support} tone="emerald" />
      <LevelCard label="Active range" value={pulse.activeRange} tone="amber" />
    </div>
  );
}


function LevelCard({ label, value, tone }) {
  const tones = {
    sky: "border-sky-200 bg-sky-50 text-sky-800",
    rose: "border-rose-200 bg-rose-50 text-rose-800",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
  };
  return <div className={clsx("rounded-xl border p-4", tones[tone])}><div className="text-[11px] uppercase tracking-[0.14em] opacity-70">{label}</div><div className="mt-2 text-base font-semibold">{value}</div></div>;
}


function buildCoinPulse(view, detail, participation) {
  const move = buildMoveAnalysis(view, detail, participation);
  const fundingRate = firstNumber(
    detail?.derivatives?.latest_funding_rate,
    detail?.derivatives?.latestFundingRate,
    detail?.derivatives?.funding?.latest?.rate
  );
  const openInterest = firstNumber(
    detail?.derivatives?.latest_open_interest,
    detail?.derivatives?.latestOpenInterest,
    detail?.derivatives?.openInterest?.latest?.value
  );
  const openInterestChange = firstNumber(
    detail?.derivatives?.latest_open_interest_change_pct,
    detail?.derivatives?.latestOpenInterestChangePct,
    detail?.derivatives?.openInterest?.latest_change_pct
  );
  const price = move.price > 0 ? `$${formatPrice(move.price, { compactSmall: true })}` : "Unavailable";
  const bias = move.move.label.replaceAll("_", " ");
  const structure = String(detail?.regimeLabel || participation?.direction || bias).replaceAll("_", " ");
  const support = move.support;
  const resistance = move.resistance;
  const levelsAvailable = support !== "Calculating" && resistance !== "Calculating";
  const intradayTone = !levelsAvailable
    ? "Directional evidence is available; price levels are still calculating"
    : move.move.score >= 40
      ? `Bullish while price holds above ${support}`
      : move.move.score <= -40
        ? `Bearish while price remains below ${resistance}`
        : `Range-bound until price confirms outside ${support} – ${resistance}`;
  const activeRange = levelsAvailable ? `${support} – ${resistance}` : "Calculating";
  const drivers = move.drivers.slice(0, 6);

  return {
    symbol: view.symbol,
    timeframe: view.timeframe,
    mode: view.mode,
    reportDate: new Intl.DateTimeFormat("en-IN", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
      timeZone: "Asia/Kolkata",
    }).format(new Date()),
    headline: pulseHeadline(view.symbol, move.move.score, support, resistance),
    bias,
    score: move.move.score,
    hasEvidence: move.hasEvidence,
    price,
    change24h: move.change24h,
    confidence: firstNumber(detail?.confidence) ?? 0,
    signalType: detail?.signalType || "WAIT",
    engines: move.engines,
    drivers,
    probabilities: move.probabilities,
    support,
    resistance,
    activeRange,
    quality: participation?.quality_state || "PENDING",
    funding: {
      display: fundingRate === null ? "Unavailable" : `${formatSigned(fundingRate * 100, 4)}%`,
      note: detail?.derivatives?.funding_trend || detail?.derivatives?.funding?.trend || "Funding feed pending",
    },
    openInterest: {
      display: openInterest === null ? "Unavailable" : formatNumber(openInterest, 0),
      note: openInterestChange === null ? "Change unavailable" : `${formatSigned(openInterestChange, 2)}% latest change`,
    },
    whatMatters: [
      { label: "Active trading range", value: activeRange },
      { label: "Nearest resistance", value: resistance },
      { label: "Nearest support", value: support },
      { label: "Market structure", value: structure },
      { label: "Current tone", value: intradayTone },
    ],
    narrative: pulseNarrative(view.symbol, bias, drivers, move.probabilities, participation),
  };
}


function pulseHeadline(symbol, score, support, resistance) {
  const levelsAvailable = support !== "Calculating" && resistance !== "Calculating";
  if (!levelsAvailable) {
    if (score >= 40) return `${symbol} carries a bullish composite bias`;
    if (score <= -40) return `${symbol} carries a bearish composite bias`;
    return `${symbol} awaits confirmed directional participation`;
  }
  if (score >= 60) return `${symbol} shows strong bullish participation above ${support}`;
  if (score >= 40) return `${symbol} builds a bullish setup below ${resistance}`;
  if (score <= -60) return `${symbol} remains under strong bearish pressure below ${resistance}`;
  if (score <= -40) return `${symbol} carries a bearish setup above ${support}`;
  return `${symbol} trades inside the active ${support} – ${resistance} range`;
}


function pulseNarrative(symbol, bias, drivers, probabilities, participation) {
  const evidence = drivers.length
    ? `The leading observed drivers are ${drivers.slice(0, 3).join("; ")}.`
    : "Directional engine evidence is still incomplete, so no driver is promoted as confirmed.";
  const quality = participation?.quality_state
    ? ` Evidence quality is ${participation.quality_state}.`
    : " Evidence quality is pending.";
  return `${symbol} currently carries a ${bias.toLowerCase()} composite bias. ${evidence} The model assigns ${formatPercent(probabilities.continuation, 0)} continuation, ${formatPercent(probabilities.pullback, 0)} pullback, and ${formatPercent(probabilities.reversal, 0)} reversal probability.${quality}`;
}


function enginePosition(score) {
  if (score === null) return "Unavailable";
  if (score >= 40) return "Bullish";
  if (score <= -40) return "Bearish";
  return "Neutral";
}


function firstNumber(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}


function numberClass(value) {
  if (value === null || value === undefined) return "text-slate-500";
  return Number(value) > 0 ? "text-emerald-600" : Number(value) < 0 ? "text-rose-600" : "text-slate-600";
}


function scoreBadge(score) {
  if (score >= 40) return "border-emerald-300/30 bg-emerald-400/15 text-emerald-100";
  if (score <= -40) return "border-rose-300/30 bg-rose-400/15 text-rose-100";
  return "border-amber-300/30 bg-amber-400/15 text-amber-100";
}
