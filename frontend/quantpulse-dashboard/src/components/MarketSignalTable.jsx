import clsx from "clsx";
import { Eye } from "lucide-react";
import { Link } from "react-router-dom";
import Pill from "./ui/Pill";
import { formatPercent, formatPrice, formatSigned } from "../utils/formatters";
import { deriveRowEligibilityState } from "../utils/eligibility";
import { formatTickAge, getLiveMarketState, liveStateClasses } from "../utils/liveMarket";

export default function MarketSignalTable({
  rows = [],
  watchlist,
  liveStatus,
  paperTradeCandidates = [],
  minConfidence = 40,
  activeSymbol,
  onOpenSymbol,
  getSymbolHref,
  title = "Market scan",
  subtitle = "Live source, AI signal, and risk context",
}) {
  const enrichedRows = rows.map((row) => enrichRow(row, watchlist, liveStatus, minConfidence, paperTradeCandidates));

  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-slate-900/70">
      <div className="flex flex-col gap-1 border-b border-white/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm font-medium text-white">{title}</div>
          <div className="text-xs text-slate-500">{subtitle}</div>
        </div>
        <div className="text-xs uppercase tracking-[0.2em] text-slate-500">{enrichedRows.length} symbols</div>
      </div>

      <div className="divide-y divide-white/5 sm:hidden">
        {enrichedRows.map((row) => (
          <MobileSignalCard
            key={row.symbol}
            row={row}
            active={activeSymbol === row.symbol}
            minConfidence={minConfidence}
            onOpenSymbol={onOpenSymbol}
            getSymbolHref={getSymbolHref}
          />
        ))}
      </div>

      <div className="hidden overflow-x-auto sm:block">
        <table className="min-w-[1040px] divide-y divide-white/5 text-left text-sm xl:min-w-[1160px]">
          <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            <tr>
              <th className="px-3 py-2.5">Symbol</th>
              <th className="px-3 py-2.5">Timeframe</th>
              <th className="px-3 py-2.5">Live price</th>
              <th className="px-3 py-2.5">AI signal</th>
              <th className="px-3 py-2.5">Confidence</th>
              <th className="px-3 py-2.5">RS score</th>
              <th className="px-3 py-2.5">Stage</th>
              <th className="px-3 py-2.5">Regime</th>
              <th className="px-3 py-2.5">Spot confirm</th>
              <th className="px-3 py-2.5">Long / short</th>
              <th className="px-3 py-2.5">Risk</th>
              <th className="px-3 py-2.5">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {enrichedRows.map((row) => (
              <tr key={row.symbol} className={clsx("transition hover:bg-white/5", activeSymbol === row.symbol && "bg-cyan-500/10")}>
                <td className="px-2.5 py-2.5 sm:px-3">
                  <div className="font-medium text-white">{row.symbol}</div>
                  <div className="text-[11px] text-slate-500">{row.watchStatus}</div>
                </td>
                <td className="px-2.5 py-2.5 sm:px-3">
                  <Pill tone="slate">{row.timeframe || "-"}</Pill>
                </td>
                <td className="px-2.5 py-2.5 sm:px-3">
                  <div className="flex items-center gap-2">
                    <div className="font-medium text-slate-100">{formatPrice(row.currentPrice, { fallback: "-", compactSmall: true })}</div>
                    <span className={clsx("inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em]", liveStateClasses(row.liveState.tone))}>
                      {row.liveState.label}
                    </span>
                  </div>
                  <div className={clsx("text-[11px]", row.liveState.tone === "emerald" ? "text-cyan-300" : row.liveState.tone === "amber" ? "text-amber-300" : "text-slate-400")}>{row.priceSource}</div>
                  <div
                    className={clsx(
                      "mt-0.5 text-[11px]",
                      row.liveChangePct === null || row.liveChangePct === undefined
                        ? "text-slate-500"
                        : row.liveChangePct > 0
                          ? "text-emerald-300"
                          : row.liveChangePct < 0
                            ? "text-rose-300"
                            : "text-slate-500"
                    )}
                  >
                    {row.liveState.state === "LIVE" && row.liveChangePct !== null && row.liveChangePct !== undefined
                      ? `1m ${formatSigned(row.liveChangePct, 2, "-")}%`
                      : formatTickAge(row.liveState.ageSeconds)}
                  </div>
                </td>
                <td className="px-2.5 py-2.5 sm:px-3">
                  <Pill tone={signalTone(row.type)}>{row.type}</Pill>
                </td>
                <td className="px-2.5 py-2.5 text-slate-300 sm:px-3">{formatPercent(row.confidence, 0, "-")}</td>
                <td className="px-2.5 py-2.5 sm:px-3">
                  <span className={clsx("font-medium", row.rsScore >= 0 ? "text-emerald-300" : "text-rose-300")}>
                    {formatSigned(row.rsScore, 0, "-")}
                  </span>
                </td>
                <td className="px-2.5 py-2.5 text-slate-300 sm:px-3">{row.stage}</td>
                <td className="px-2.5 py-2.5 text-slate-300 sm:px-3">{row.regime}</td>
                <td className="px-2.5 py-2.5 sm:px-3">
                  <Pill tone={row.participationTone}>{row.participationDirection}</Pill>
                  <div className="mt-1 text-[11px] text-slate-400">
                    {formatSigned(row.participationScore, 0, "-")} · {formatPercent(row.participationConfidence, 0, "-")}
                  </div>
                </td>
                <td className="px-2.5 py-2.5 sm:px-3">
                  <div className="flex min-w-28 overflow-hidden rounded-full bg-slate-950/80">
                    <div className="h-2 bg-emerald-400" style={{ width: `${row.longPct}%` }} />
                    <div className="h-2 bg-rose-400" style={{ width: `${row.shortPct}%` }} />
                  </div>
                  <div className="mt-1 text-[11px] text-slate-400">
                    {formatPercent(row.longPct, 0)} / {formatPercent(row.shortPct, 0)}
                  </div>
                </td>
                <td className="w-[190px] px-2.5 py-2.5 align-top sm:w-[210px] sm:px-3">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Pill tone={row.riskTone}>{row.riskLabel}</Pill>
                    <Pill tone={row.executorTone}>{row.executorLabel}</Pill>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-500">
                    <span>{riskSourceLabel(row.riskSource)}</span>
                    <span>RR {formatSigned(row.riskReward, 2, "-")}</span>
                    {row.riskLabel === "Blocked by confidence" ? <span>Min conf {minConfidence}</span> : null}
                  </div>
                  {(row.executorNote || row.riskNote) ? (
                    <div
                      className="mt-1 max-w-[10rem] line-clamp-3 text-[11px] leading-4 text-slate-500 sm:max-w-[12rem]"
                      title={row.executorNote || row.riskNote}
                    >
                      {row.executorNote || row.riskNote}
                    </div>
                  ) : null}
                </td>
                <td className="px-2.5 py-2.5 sm:px-3">
                  <DetailAction row={row} onOpenSymbol={onOpenSymbol} getSymbolHref={getSymbolHref} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MobileSignalCard({ row, active, minConfidence, onOpenSymbol, getSymbolHref }) {
  return (
    <article className={clsx("min-w-0 p-3", active && "bg-cyan-500/10")}>
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white">{row.symbol}</span>
            <Pill tone="slate">{row.timeframe || "-"}</Pill>
            <span className={clsx("inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em]", liveStateClasses(row.liveState.tone))}>
              {row.liveState.label}
            </span>
          </div>
          <div className="mt-1 text-lg font-semibold text-slate-100">
            {formatPrice(row.currentPrice, { fallback: "-", compactSmall: true })}
          </div>
          <div className="text-[11px] text-slate-500">{row.priceSource} | {formatTickAge(row.liveState.ageSeconds)}</div>
        </div>
        <DetailAction row={row} onOpenSymbol={onOpenSymbol} getSymbolHref={getSymbolHref} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <MobileDatum label="Signal" value={<Pill tone={signalTone(row.type)}>{row.type}</Pill>} />
        <MobileDatum label="Confidence" value={formatPercent(row.confidence, 0, "-")} />
        <MobileDatum label="Regime" value={row.regime} />
        <MobileDatum
          label="Spot confirm"
          value={`${row.participationDirection} ${formatSigned(row.participationScore, 0, "-")} · ${formatPercent(row.participationConfidence, 0, "-")}`}
          valueClass={row.participationTone === "emerald" ? "text-emerald-300" : row.participationTone === "rose" ? "text-rose-300" : "text-amber-300"}
        />
        <MobileDatum label="Stage" value={row.stage} />
        <MobileDatum label="Long / short" value={`${formatPercent(row.longPct, 0)} / ${formatPercent(row.shortPct, 0)}`} />
        <MobileDatum label="RS score" value={formatSigned(row.rsScore, 0, "-")} valueClass={row.rsScore >= 0 ? "text-emerald-300" : "text-rose-300"} />
      </div>

      <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/60 p-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Pill tone={row.riskTone}>{row.riskLabel}</Pill>
          <Pill tone={row.executorTone}>{row.executorLabel}</Pill>
          <span className="text-[11px] text-slate-500">RR {formatSigned(row.riskReward, 2, "-")}</span>
        </div>
        {row.riskLabel === "Blocked by confidence" ? <div className="mt-1 text-[11px] text-slate-500">Minimum confidence {minConfidence}</div> : null}
        {(row.executorNote || row.riskNote) ? <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{row.executorNote || row.riskNote}</div> : null}
      </div>
    </article>
  );
}

function MobileDatum({ label, value, valueClass = "text-slate-200" }) {
  return (
    <div className="min-w-0 rounded-lg border border-white/10 bg-slate-950/55 px-2.5 py-2">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className={clsx("mt-1 min-w-0 break-words font-medium", valueClass)}>{value}</div>
    </div>
  );
}

function DetailAction({ row, onOpenSymbol, getSymbolHref }) {
  const className =
    "inline-flex items-center gap-2 rounded-lg border border-white/10 bg-slate-950/70 px-2.5 py-1.5 text-xs font-medium text-cyan-200 transition hover:border-cyan-400/40 hover:bg-cyan-500/10";

  if (getSymbolHref) {
    return (
      <Link to={getSymbolHref(row.symbol)} className={className}>
        <Eye className="h-3.5 w-3.5" />
        Details
      </Link>
    );
  }

  return (
    <button type="button" onClick={() => onOpenSymbol?.(row.symbol)} className={className}>
      <Eye className="h-3.5 w-3.5" />
      Details
    </button>
  );
}

export function enrichRow(row, watchlist, liveStatus, minConfidence = 40, paperTradeCandidates = []) {
  const watchRow = (watchlist?.records || []).find((item) => item.symbol === row.symbol) || {};
  const selectedRow = selectWatchlistSignal(row, watchRow);
  const rsScore = resolveRsScore(selectedRow, watchRow);
  const longPct = resolveDirectionalPct(selectedRow, "LONG");
  const shortPct = resolveDirectionalPct(selectedRow, "SHORT");
  const riskReward = numberFrom(selectedRow.riskReward, watchRow.risk_reward, 0);
  const stage = inferStage(selectedRow, watchRow);
  const risk = deriveRowEligibilityState({ row: selectedRow, watchRow, minConfidence });
  const hasLiveRecord = Boolean(row.liveUpdatedAt);
  const liveState = getLiveMarketState({ liveStatus, updatedAt: row.liveUpdatedAt, hasLiveRecord });
  const executor = deriveExecutorState(selectedRow, paperTradeCandidates);
  const participation = watchRow.market_participation || {};

  return {
    ...selectedRow,
    currentPrice: nullableNumberFrom(row.currentPrice, watchRow.current_price),
    priceSource: liveState.source,
    liveState,
    rsScore,
    stage,
    regime: selectedRow.regime || watchRow.overall_bias || "WAIT",
    watchStatus: watchRow.status || "SCAN",
    longPct,
    shortPct,
    participationDirection: String(participation.direction || "UNAVAILABLE").toUpperCase(),
    participationScore: nullableNumberFrom(participation.score),
    participationConfidence: nullableNumberFrom(participation.confidence),
    participationStatus: participation.status || "UNAVAILABLE",
    participationTone: participationTone(participation),
    riskReward,
    riskLabel: risk.label,
    riskTone: risk.tone,
    riskNote: risk.note,
    executorStatus: executor.status,
    executorLabel: executor.label,
    executorTone: executor.tone,
    executorNote: executor.note,
  };
}

export function selectWatchlistSignal(row, watchRow) {
  const status = String(watchRow?.status || "").toUpperCase();
  const side = normalizeTradeSide(watchRow?.side);
  if (status !== "READY" || !["LONG", "SHORT"].includes(side)) return row;

  const watchTargets = [watchRow.target1, watchRow.target2].filter(
    (value) => value !== null && value !== undefined
  );

  return {
    ...row,
    timeframe: watchRow.entry_timeframe || row.timeframe,
    type: side === "LONG" ? "BUY" : "SELL",
    confidence: numberFrom(watchRow.confidence, row.confidence),
    signalScore: numberFrom(watchRow.entry_score, row.signalScore),
    signalBias: watchRow.entry_bias || row.signalBias,
    regime: watchRow.entry_bias || watchRow.overall_bias || row.regime,
    entry: nullableNumberFrom(watchRow.entry, row.entry),
    stopLoss: nullableNumberFrom(watchRow.stop_loss, row.stopLoss),
    targets: watchTargets.length ? watchTargets : row.targets,
    riskReward: nullableNumberFrom(watchRow.risk_reward, row.riskReward),
    selectedFromWatchlist: true,
  };
}

export function deriveExecutorState(row, candidates = []) {
  const side = normalizeTradeSide(row.type);
  const candidate = candidates.find(
    (item) =>
      String(item?.symbol || "").toUpperCase() === String(row.symbol || "").toUpperCase() &&
      normalizeTradeSide(item?.side) === side
  );

  if (!candidate) {
    return {
      status: "NO_QUEUED_PLAN",
      label: "No queued plan",
      tone: "amber",
      note: "Executor has no OPEN trade plan queued for this symbol/side.",
    };
  }

  const riskFreshness = candidate?.risk_decision?.freshness || null;
  if (riskFreshness?.is_stale) {
    return {
      status: "STALE",
      label: "Risk stale",
      tone: "amber",
      note: `Queued OPEN trade plan exists, but ${staleFreshnessNote(riskFreshness, "risk decision")}.`,
    };
  }

  if (candidate.eligible) {
    return {
      status: "READY",
      label: "Executor ready",
      tone: "emerald",
      note: "Queued OPEN trade plan passes executor checks.",
    };
  }

  return {
    status: "BLOCKED",
    label: "Executor blocked",
    tone: "rose",
    note: candidate.blocked_reasons?.[0] || "Queued OPEN trade plan is blocked.",
  };
}

function normalizeTradeSide(value) {
  const side = String(value || "").toUpperCase();
  if (["BUY", "LONG", "STRONG_LONG"].includes(side)) return "LONG";
  if (["SELL", "SHORT", "STRONG_SHORT"].includes(side)) return "SHORT";
  return side || null;
}

function signalTone(type) {
  if (type === "BUY") return "emerald";
  if (type === "SELL") return "rose";
  return "slate";
}

function participationTone(participation) {
  if (participation?.allowed) return "emerald";
  const status = String(participation?.status || "").toUpperCase();
  if (["STALE", "DEGRADED", "UNAVAILABLE", "BELOW_THRESHOLD"].includes(status)) return "amber";
  return "rose";
}

function riskSourceLabel(source) {
  const value = String(source || "").toLowerCase();
  if (value === "persisted") return "Persisted";
  if (value === "computed") return "Computed";
  return "Fallback";
}

function riskSourceTone(source) {
  const value = String(source || "").toLowerCase();
  if (value === "persisted") return "cyan";
  if (value === "computed") return "amber";
  return "slate";
}

function staleFreshnessNote(freshness, label) {
  const ageSeconds = Number(freshness?.data_age_seconds);
  if (Number.isFinite(ageSeconds) && ageSeconds >= 0) {
    return `${label} is stale (${formatAgeShort(ageSeconds)} old)`;
  }
  return `${label} is stale`;
}

function formatAgeShort(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "unknown age";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function directionalPct(type, confidence, side) {
  const value = Math.max(0, Math.min(Number(confidence) || 0, 100));
  if (type === "BUY") return side === "LONG" ? value : 100 - value;
  if (type === "SELL") return side === "SHORT" ? value : 100 - value;
  return 50;
}

function resolveDirectionalPct(row, side) {
  if (row?.selectedFromWatchlist) {
    return directionalPct(row.type, row.confidence, side);
  }
  const probabilityPrimary = side === "LONG" ? "probabilityLong" : "probabilityShort";
  const probabilitySecondary = side === "LONG" ? "probability_long" : "probability_short";
  const probabilityTertiary = side === "LONG" ? "longProbability" : "shortProbability";
  const probabilityQuaternary = side === "LONG" ? "long_probability" : "short_probability";
  const primary = side === "LONG" ? "longPct" : "shortPct";
  const secondary = side === "LONG" ? "longSidePct" : "shortSidePct";
  const fallback = directionalPct(row.type, row.confidence, side);
  const raw = numberFrom(
    row[probabilityPrimary],
    row[probabilitySecondary],
    row[probabilityTertiary],
    row[probabilityQuaternary],
    row[primary],
    row[secondary]
  );

  if (raw !== 50) {
    return raw;
  }

  const bias = String(row.signalBias || row.regime || "").toUpperCase();
  const score = Number(row.signalScore);

  if (bias.includes("LONG")) {
    return side === "LONG" ? 60 : 40;
  }

  if (bias.includes("SHORT")) {
    return side === "LONG" ? 40 : 60;
  }

  if (Number.isFinite(score) && score !== 0) {
    const strength = Math.max(-100, Math.min(100, score));
    const adjusted = 50 + strength / 2;
    return side === "LONG"
      ? Math.max(0, Math.min(100, adjusted))
      : Math.max(0, Math.min(100, 100 - adjusted));
  }

  return fallback;
}

function resolveRsScore(row, watchRow) {
  const timeframeKey = scoreKeyForTimeframe(row.timeframe);
  return numberFrom(
    row.signalScore,
    row.selectedFromWatchlist ? watchRow?.entry_score : null,
    timeframeKey ? watchRow?.[timeframeKey] : null,
    watchRow?.score_1d,
    watchRow?.score_4h,
    watchRow?.score_2h,
    watchRow?.score_1h,
    watchRow?.score_15m,
    watchRow?.score_5m,
    watchRow?.rs_score,
    row.confidence - 50
  );
}

function scoreKeyForTimeframe(timeframe) {
  return {
    "5m": "score_5m",
    "15m": "score_15m",
    "1h": "score_1h",
    "2h": "score_2h",
    "4h": "score_4h",
    "1d": "score_1d",
  }[String(timeframe || "").toLowerCase()] || null;
}

function inferStage(row, watchRow) {
  const timeframeBias = timeframeBiasForRow(row, watchRow);
  const primaryText = `${row.regime || ""} ${timeframeBias || ""}`.trim().toUpperCase();
  const fallbackText = `${watchRow.overall_bias || ""} ${watchRow.bias_1d || ""} ${watchRow.bias_4h || ""} ${watchRow.bias_2h || ""} ${watchRow.bias_1h || ""} ${watchRow.bias_15m || ""} ${watchRow.bias_5m || ""}`.toUpperCase();
  const text = primaryText || fallbackText;
  if (row.type === "BUY" || text.includes("BULL") || text.includes("LONG")) return "Stage 2 Uptrend";
  if (row.type === "SELL" || text.includes("BEAR") || text.includes("SHORT")) return "Stage 4 Downtrend";
  if (text.includes("RANGE") || text.includes("MIXED")) return "Stage 1 Base";
  return "Stage 3 Transition";
}

function timeframeBiasForRow(row, watchRow) {
  return {
    "5m": watchRow?.bias_5m,
    "15m": watchRow?.bias_15m,
    "1h": watchRow?.bias_1h,
    "2h": watchRow?.bias_2h,
    "4h": watchRow?.bias_4h,
    "1d": watchRow?.bias_1d,
  }[String(row?.timeframe || "").toLowerCase()] || null;
}

function numberFrom(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return 0;
}

function nullableNumberFrom(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}
