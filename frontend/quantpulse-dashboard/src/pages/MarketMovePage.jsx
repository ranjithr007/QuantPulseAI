import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Gauge,
  RefreshCw,
  ShieldCheck,
  Target,
  Zap,
} from "lucide-react";
import { loadMarketParticipationTrends } from "../hooks/dashboardApi";
import { formatNumber, formatPercent, formatPrice, formatSigned } from "../utils/formatters";
import Pill from "../components/ui/Pill";

export default function MarketMovePage({ view, selectedDetail }) {
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
          setError(requestError?.message || "Market move evidence is unavailable");
        }
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [refreshKey]);

  const participation = (payload?.records || []).find(
    (record) => String(record?.symbol || "").toUpperCase() === String(view.symbol || "").toUpperCase()
  ) || null;
  const analysis = useMemo(
    () => buildMoveAnalysis(view, selectedDetail, participation),
    [view, selectedDetail, participation]
  );

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Multi-engine intelligence</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Market move</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-400">
              A directional summary of live price, liquidations, order flow, whales, SMC, regime and verified macro evidence.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setRefreshKey((value) => value + 1)}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/10 bg-slate-900 px-3 text-sm text-slate-200 hover:border-cyan-400/30"
          >
            <RefreshCw className={clsx("h-4 w-4", loading && "animate-spin")} /> Refresh evidence
          </button>
        </div>

        {error ? (
          <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 p-3 text-sm text-rose-200">
            {error}
          </div>
        ) : null}

        <div className="mt-3.5 grid gap-3 xl:grid-cols-[0.82fr_1.18fr]">
          <div className="space-y-3">
            <MarketMoveSummary analysis={analysis} loading={loading} />
            <EngineScoreCard engines={analysis.engines} />
          </div>

          <div className="space-y-3">
            <DriverCard drivers={analysis.drivers} />
            <ProbabilityCard probabilities={analysis.probabilities} />
            <div className="grid gap-3 sm:grid-cols-2">
              <ZoneCard
                title="Next resistance"
                value={analysis.resistance}
                note={analysis.resistanceNote}
                tone="rose"
                icon={ArrowUp}
              />
              <ZoneCard
                title="Major support"
                value={analysis.support}
                note={analysis.supportNote}
                tone="emerald"
                icon={ArrowDown}
              />
            </div>
            <EvidencePolicy
              macroAvailable={analysis.macroAvailable}
              macroProvider={analysis.macroProvider}
              macroStatus={analysis.macroStatus}
              quality={participation?.quality_state}
            />
          </div>
        </div>
        <MarketContextCard analysis={analysis} />
      </div>
    </section>
  );
}

function MarketContextCard({ analysis }) {
  const metrics = [
    {
      label: "Executable signal",
      value: analysis.signalType,
      note: analysis.confidence === null ? "Confidence unavailable" : `${formatPercent(analysis.confidence, 1)} confidence`,
    },
    {
      label: "Funding rate",
      value: analysis.fundingRate === null ? "Unavailable" : `${formatSigned(analysis.fundingRate * 100, 4)}%`,
      note: analysis.fundingTrend,
    },
    {
      label: "Open interest",
      value: analysis.openInterest === null ? "Unavailable" : formatNumber(analysis.openInterest, 0),
      note: analysis.openInterestChange === null ? "Change unavailable" : `${formatSigned(analysis.openInterestChange, 2)}% latest change`,
    },
    {
      label: "Market structure",
      value: analysis.marketStructure,
      note: `${analysis.timeframe} · ${analysis.mode}`,
    },
  ];

  return (
    <article className="mt-3 rounded-xl border border-white/10 bg-slate-900/70 p-4">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 text-sm font-medium text-white">
          <Activity className="h-4 w-4 text-cyan-300" /> Trading context
        </div>
        <div className="text-xs text-slate-500">Futures and execution evidence for the selected coin</div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => (
          <div key={metric.label} className="rounded-lg border border-white/5 bg-slate-950/55 p-3">
            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{metric.label}</div>
            <div className="mt-2 text-base font-semibold text-white">{metric.value}</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">{metric.note}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-[0.34fr_0.66fr]">
        <div className="rounded-lg border border-white/5 bg-slate-950/55 p-3">
          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Active range</div>
          <div className="mt-2 text-base font-semibold text-white">{analysis.activeRange}</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">{analysis.currentTone}</div>
        </div>
        <div className="rounded-lg border border-white/5 bg-slate-950/55 p-3">
          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Market intelligence</div>
          <p className="mt-2 text-sm leading-6 text-slate-300">{analysis.narrative}</p>
        </div>
      </div>
    </article>
  );
}

function MarketMoveSummary({ analysis, loading }) {
  const DirectionIcon = analysis.move.score > 0 ? ArrowUp : analysis.move.score < 0 ? ArrowDown : Activity;
  return (
    <article className="overflow-hidden rounded-xl border border-white/10 bg-slate-900/75">
      <div className="border-b border-white/10 bg-gradient-to-r from-cyan-500/10 via-transparent to-transparent p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xl font-semibold text-white sm:text-2xl">{analysis.symbol}</div>
            <div className="mt-1 text-2xl font-semibold tracking-tight text-white sm:text-3xl">
              {analysis.price > 0 ? `$${formatPrice(analysis.price, { compactSmall: true })}` : "Price unavailable"}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">24H</div>
            <div className={clsx("mt-1 text-lg font-semibold", numberTone(analysis.change24h))}>
              {analysis.change24h === null ? "N/A" : formatSigned(analysis.change24h, 2) + "%"}
            </div>
          </div>
        </div>
      </div>
      <div className="p-4">
        <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Current move</div>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <div className={clsx("grid h-10 w-10 place-items-center rounded-lg border", moveIconClasses(analysis.move.tone))}>
            <DirectionIcon className="h-5 w-5" />
          </div>
          <div>
            <div className={clsx("text-xl font-semibold", moveTextClass(analysis.move.tone))}>
              {loading && !analysis.hasEvidence ? "CALCULATING" : analysis.move.label}
            </div>
            <div className="mt-0.5 text-xs text-slate-500">
              Composite score {formatSigned(analysis.move.score, 0)} · {analysis.availableEngineCount}/6 engines available
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

function EngineScoreCard({ engines }) {
  return (
    <article className="rounded-xl border border-white/10 bg-slate-900/70 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-white">
        <Gauge className="h-4 w-4 text-cyan-300" /> Engine scores
      </div>
      <div className="mt-4 space-y-3">
        {engines.map((engine) => (
          <div key={engine.label}>
            <div className="grid grid-cols-[92px_48px_1fr] items-center gap-2 text-xs sm:grid-cols-[110px_52px_1fr]">
              <span className="text-slate-300">{engine.label}</span>
              <span className={clsx("text-right font-semibold", engine.score === null ? "text-slate-500" : numberTone(engine.score))}>
                {engine.score === null ? "N/A" : formatSigned(engine.score, 0)}
              </span>
              <ScoreBar score={engine.score} />
            </div>
            <div className="mt-1 pl-[150px] text-[10px] leading-4 text-slate-500 sm:pl-[178px]">{engine.reason}</div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between text-[10px] uppercase tracking-[0.14em] text-slate-600">
        <span>−100 bearish</span><span>0 neutral</span><span>+100 bullish</span>
      </div>
    </article>
  );
}

function ScoreBar({ score }) {
  if (score === null) {
    return <div className="h-2 rounded-full bg-slate-800" />;
  }
  const value = clamp(score, -100, 100);
  const width = Math.abs(value) / 2;
  return (
    <div className="relative h-2 overflow-hidden rounded-full bg-slate-800">
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-500/60" />
      <div
        className={clsx("absolute inset-y-0 rounded-full", value >= 0 ? "bg-emerald-400" : "bg-rose-400")}
        style={{ left: value >= 0 ? "50%" : `${50 - width}%`, width: `${width}%` }}
      />
    </div>
  );
}

function DriverCard({ drivers }) {
  return (
    <article className="rounded-xl border border-white/10 bg-slate-900/70 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-white"><Zap className="h-4 w-4 text-amber-300" />Primary drivers</div>
      <ol className="mt-3 space-y-2">
        {drivers.map((driver, index) => (
          <li key={`${driver}-${index}`} className="flex gap-3 rounded-lg border border-white/5 bg-slate-950/55 px-3 py-2.5 text-sm text-slate-300">
            <span className="font-semibold text-cyan-300">{index + 1}.</span><span>{driver}</span>
          </li>
        ))}
        {!drivers.length ? <li className="text-sm text-slate-500">Waiting for directional engine evidence.</li> : null}
      </ol>
    </article>
  );
}

function ProbabilityCard({ probabilities }) {
  return (
    <article className="rounded-xl border border-white/10 bg-slate-900/70 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-white"><Target className="h-4 w-4 text-cyan-300" />Probability</div>
      <div className="mt-3 space-y-3">
        <ProbabilityRow label="Continuation" value={probabilities.continuation} tone="emerald" />
        <ProbabilityRow label="Pullback" value={probabilities.pullback} tone="amber" />
        <ProbabilityRow label="Reversal" value={probabilities.reversal} tone="rose" />
      </div>
      <div className="mt-3 text-xs text-slate-500">Scenario probabilities are derived from the current composite strength and always total 100%.</div>
    </article>
  );
}

function ProbabilityRow({ label, value, tone }) {
  const fill = tone === "emerald" ? "bg-emerald-400" : tone === "rose" ? "bg-rose-400" : "bg-amber-400";
  return (
    <div>
      <div className="flex items-center justify-between text-sm"><span className="text-slate-300">{label}</span><span className="font-semibold text-white">{formatPercent(value, 0)}</span></div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800"><div className={clsx("h-full rounded-full", fill)} style={{ width: `${value}%` }} /></div>
    </div>
  );
}

function ZoneCard({ title, value, note, tone, icon: Icon }) {
  const color = tone === "emerald" ? "text-emerald-300" : "text-rose-300";
  return (
    <article className="rounded-xl border border-white/10 bg-slate-900/70 p-4">
      <div className={clsx("flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em]", color)}><Icon className="h-4 w-4" />{title}</div>
      <div className="mt-3 text-lg font-semibold text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{note}</div>
    </article>
  );
}

function EvidencePolicy({ macroAvailable, macroProvider, macroStatus, quality }) {
  const macroMessage = macroAvailable
    ? "Macro scoring is backed by a verified provider."
    : macroProvider
      ? `${macroProvider} is connected but currently ${macroStatus || "DEGRADED"}; its advisory score is excluded until the evidence is verified.`
      : "Macro stays N/A until a verified provider is connected; news or Treasury drivers are never inferred or fabricated.";
  return (
    <div className="flex items-start gap-2 rounded-lg border border-white/10 bg-slate-950/60 p-3 text-xs leading-5 text-slate-400">
      {macroAvailable ? <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />}
      <span>
        Market evidence quality: <strong className="text-slate-200">{quality || "PENDING"}</strong>. {macroMessage}
      </span>
    </div>
  );
}

function buildMoveAnalysis(view, detail, participation) {
  const engines = buildEngines(detail, participation);
  const usableScores = engines.map((engine) => engine.score).filter((score) => score !== null);
  const participationScore = optionalNumber(participation?.score);
  const compositeScore = clamp(
    usableScores.length ? average(usableScores) : participationScore ?? 0,
    -100,
    100
  );
  const move = moveState(compositeScore);
  const timeframeEvidence = (participation?.spot?.timeframes || []).find(
    (row) => String(row?.timeframe).toLowerCase() === String(view.timeframe).toLowerCase()
  ) || (participation?.spot?.timeframes || [])[0] || null;
  const resistanceZone = timeframeEvidence?.resistance;
  const supportZone = timeframeEvidence?.support;
  const macroAvailable = participation?.external_context?.status === "VERIFIED";
  const participationDerivatives = participation?.derivatives || null;
  const fundingRate = participationDerivatives
    ? optionalNumber(participationDerivatives.funding_rate)
    : optionalNumber(
      detail?.derivatives?.latest_funding_rate
      ?? detail?.derivatives?.latestFundingRate
      ?? detail?.derivatives?.funding?.latest?.rate
    );
  const openInterestFresh = participationDerivatives
    ? participationDerivatives?.freshness?.open_interest?.is_stale === false
    : true;
  const openInterest = openInterestFresh
    ? optionalNumber(
      detail?.derivatives?.latest_open_interest
      ?? detail?.derivatives?.latestOpenInterest
      ?? detail?.derivatives?.openInterest?.latest?.value
    )
    : null;
  const openInterestChange = participationDerivatives
    ? optionalNumber(participationDerivatives.open_interest_change_percent)
    : optionalNumber(
      detail?.derivatives?.latest_open_interest_change_pct
      ?? detail?.derivatives?.latestOpenInterestChangePct
      ?? detail?.derivatives?.openInterest?.latest_change_pct
    );
  const resistance = formatZone(resistanceZone, detail?.resistanceLevels?.r1, detail?.resistanceLevels?.r2);
  const support = formatZone(supportZone, detail?.supportLevels?.s2, detail?.supportLevels?.s1);
  const levelsAvailable = resistance !== "Calculating" && support !== "Calculating";
  const drivers = buildDrivers(engines, participation, move.score);
  const probabilities = scenarioProbabilities(move.score);
  const marketStructure = String(detail?.regimeLabel || participation?.direction || move.label).replaceAll("_", " ");
  const activeRange = levelsAvailable ? `${support} – ${resistance}` : "Calculating";
  const currentTone = !levelsAvailable
    ? "Directional evidence is available; price levels are still calculating"
    : move.score >= 40
      ? `Bullish while price holds above ${support}`
      : move.score <= -40
        ? `Bearish while price remains below ${resistance}`
        : `Range-bound until price confirms outside the active range`;

  return {
    symbol: view.symbol,
    timeframe: view.timeframe,
    mode: view.mode,
    price: optionalNumber(detail?.currentPrice) || 0,
    change24h: optionalNumber(detail?.liveMarket?.price_change_pct ?? detail?.liveMarket?.price_change_percent),
    engines,
    move,
    hasEvidence: usableScores.length > 0 || participationScore !== null,
    availableEngineCount: usableScores.length,
    drivers,
    probabilities,
    resistance,
    resistanceNote: zoneNote(resistanceZone, "Nearest calculated resistance zone"),
    support,
    supportNote: zoneNote(supportZone, "Nearest calculated support zone"),
    macroAvailable,
    macroProvider: participation?.external_context?.inputs?.provider || null,
    macroStatus: participation?.external_context?.status || "UNAVAILABLE",
    signalType: detail?.signalType || "WAIT",
    confidence: optionalNumber(detail?.confidence),
    fundingRate,
    fundingTrend: fundingRate === null
      ? "Fresh funding evidence unavailable"
      : detail?.derivatives?.funding_trend || detail?.derivatives?.funding?.trend || "Funding is fresh",
    openInterest,
    openInterestChange,
    marketStructure,
    activeRange,
    currentTone,
    narrative: buildMarketNarrative(view.symbol, move, drivers, probabilities, participation?.quality_state, usableScores.length),
  };
}

function buildMarketNarrative(symbol, move, drivers, probabilities, quality, engineCount) {
  const leadingEvidence = drivers.length
    ? `Leading evidence: ${drivers.slice(0, 3).join("; ")}.`
    : "No directional driver has enough verified evidence to be promoted yet.";
  return `${symbol} has a ${move.label.toLowerCase()} composite bias from ${engineCount}/6 available engines. ${leadingEvidence} The scenario model assigns ${formatPercent(probabilities.continuation, 0)} continuation, ${formatPercent(probabilities.pullback, 0)} pullback, and ${formatPercent(probabilities.reversal, 0)} reversal probability. Evidence quality is ${quality || "PENDING"}.`;
}

function buildEngines(detail, participation) {
  const breakdown = Object.fromEntries((detail?.breakdown || []).map((item) => [item.label, item]));
  const macroContext = participation?.external_context || {};
  const macroInput = optionalNumber(macroContext?.inputs?.macro_score);
  const macroScore = macroContext.status === "VERIFIED"
    ? normalizeExternalScore(macroInput ?? macroContext.score)
    : null;
  const liquidation = participation?.liquidation || {};
  const liquidationObserved = liquidation.data_quality === "OBSERVED";
  const liquidationScore = liquidationObserved
    ? liquidation.bias === "HUNT_SHORTS" ? 100 : liquidation.bias === "HUNT_LONGS" ? -100 : normalizeComponent(participation?.components?.liquidation, 8)
    : null;
  const orderFlow = breakdown["Order flow"];
  const smc = breakdown.SMC;
  const regime = breakdown.Regime;
  const whaleScore = whaleImbalance(detail);

  return [
    {
      label: "Macro",
      score: macroScore,
      reason: macroScore === null
        ? macroInput === null
          ? "Verified macro provider not connected"
          : `${macroContext?.inputs?.provider || "Macro provider"} is ${macroContext.status || "DEGRADED"}; advisory ${formatSigned(normalizeExternalScore(macroInput), 0)} excluded from composite`
        : macroContext?.inputs?.reasons?.[0] || "Verified FRED macro context",
    },
    { label: "Liquidations", score: liquidationScore, reason: liquidationReason(liquidation) },
    { label: "Order Flow", score: componentScore(orderFlow, 25, Boolean(detail?.selectedOrderflow)), reason: orderFlow?.reason || "Order-flow evidence pending" },
    { label: "Whales", score: whaleScore, reason: whaleReason(detail, whaleScore) },
    { label: "SMC", score: componentScore(smc, 30, Boolean(detail?.selectedSmc)), reason: smc?.reason || "SMC evidence pending" },
    { label: "Regime", score: componentScore(regime, 50, Boolean(detail?.regimeLabel && detail.regimeLabel !== "WAIT")), reason: regime?.reason || detail?.regimeReason || "Regime evidence pending" },
  ];
}

function buildDrivers(engines, participation, compositeScore) {
  const direction = Math.sign(compositeScore);
  const aligned = engines
    .filter((engine) => engine.score !== null && (direction === 0 || Math.sign(engine.score) === direction) && Math.abs(engine.score) >= 5)
    .sort((left, right) => Math.abs(right.score) - Math.abs(left.score))
    .map((engine) => engine.reason);
  const participationReasons = (participation?.reasons || []).filter(validDriver);
  return [...new Set([...aligned, ...participationReasons])].filter(validDriver).slice(0, 5);
}

function validDriver(value) {
  const text = String(value || "").trim();
  return Boolean(text) && !/^no\s/i.test(text) && !/pending|unavailable|not connected/i.test(text);
}

function scenarioProbabilities(score) {
  const strength = Math.abs(clamp(score, -100, 100));
  const continuation = Math.round(clamp(50 + strength * 0.35, 50, 85));
  const reversal = Math.round(clamp(15 - strength * 0.15, 5, 15));
  return { continuation, pullback: 100 - continuation - reversal, reversal };
}

function moveState(score) {
  if (score >= 70) return { label: "STRONG BULLISH", tone: "emerald", score };
  if (score >= 40) return { label: "BULLISH", tone: "emerald", score };
  if (score >= 15) return { label: "WEAK BULLISH", tone: "cyan", score };
  if (score <= -70) return { label: "STRONG BEARISH", tone: "rose", score };
  if (score <= -40) return { label: "BEARISH", tone: "rose", score };
  if (score <= -15) return { label: "WEAK BEARISH", tone: "amber", score };
  return { label: "NEUTRAL", tone: "slate", score };
}

function whaleImbalance(detail) {
  const buy = Math.max(0, optionalNumber(detail?.whaleBuyVolume) ?? optionalNumber(detail?.whaleBuyCount) ?? 0);
  const sell = Math.max(0, optionalNumber(detail?.whaleSellVolume) ?? optionalNumber(detail?.whaleSellCount) ?? 0);
  const total = buy + sell;
  return total > 0 ? Math.round(clamp(((buy - sell) / total) * 100, -100, 100)) : null;
}

function whaleReason(detail, score) {
  if (score === null) return "Whale evidence pending";
  if (score > 5) return `Whale buying leads selling (${detail?.whaleBuyCount || 0} vs ${detail?.whaleSellCount || 0})`;
  if (score < -5) return `Whale selling leads buying (${detail?.whaleSellCount || 0} vs ${detail?.whaleBuyCount || 0})`;
  return "Whale activity is balanced";
}

function liquidationReason(liquidation) {
  if (liquidation?.data_quality !== "OBSERVED") return liquidation?.reason || "Observed liquidation feed unavailable";
  if (liquidation.bias === "HUNT_SHORTS") return "Short liquidation cascade pressure";
  if (liquidation.bias === "HUNT_LONGS") return "Long liquidation cascade pressure";
  return "Liquidation pressure is balanced";
}

function normalizeComponent(value, expectedMaximum) {
  const number = optionalNumber(value);
  return number === null ? null : Math.round(clamp((number / expectedMaximum) * 100, -100, 100));
}

function componentScore(component, expectedMaximum, hasSourceRecord) {
  if (!component) return null;
  const reason = String(component.reason || "").trim();
  const score = optionalNumber(component.score);
  if (score === null || (score === 0 && !hasSourceRecord && /^no\s/i.test(reason))) return null;
  return normalizeComponent(score, expectedMaximum);
}

function normalizeExternalScore(value) {
  const number = optionalNumber(value);
  if (number === null) return null;
  return Math.round(clamp(Math.abs(number) <= 10 ? number * 10 : number, -100, 100));
}

function formatZone(zone, fallbackLower, fallbackUpper) {
  const lower = optionalNumber(zone?.lower) ?? optionalNumber(fallbackLower);
  const upper = optionalNumber(zone?.upper) ?? optionalNumber(fallbackUpper);
  if (lower === null && upper === null) return "Calculating";
  if (lower === null || upper === null) return `$${formatPrice(lower ?? upper, { compactSmall: true })}`;
  const ordered = [lower, upper].sort((left, right) => left - right);
  return `$${formatPrice(ordered[0], { compactSmall: true })}–$${formatPrice(ordered[1], { compactSmall: true })}`;
}

function zoneNote(zone, fallback) {
  if (!zone) return fallback;
  const state = zone.breakout_accepted ? "Breakout accepted" : zone.breakdown_accepted ? "Breakdown accepted" : zone.latest_rejected ? "Latest test rejected" : `${zone.tests || 0} historical tests`;
  return `${state}${optionalNumber(zone.distance_percent) === null ? "" : ` · ${formatSigned(zone.distance_percent, 2)}% from price`}`;
}

function optionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function average(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, Number(value) || 0));
}

function numberTone(value) {
  if (value === null) return "text-slate-500";
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-slate-300";
}

function moveTextClass(tone) {
  return { emerald: "text-emerald-300", rose: "text-rose-300", cyan: "text-cyan-300", amber: "text-amber-300", slate: "text-slate-200" }[tone];
}

function moveIconClasses(tone) {
  return {
    emerald: "border-emerald-400/25 bg-emerald-500/10 text-emerald-300",
    rose: "border-rose-400/25 bg-rose-500/10 text-rose-300",
    cyan: "border-cyan-400/25 bg-cyan-500/10 text-cyan-300",
    amber: "border-amber-400/25 bg-amber-500/10 text-amber-300",
    slate: "border-white/10 bg-slate-800 text-slate-300",
  }[tone];
}
