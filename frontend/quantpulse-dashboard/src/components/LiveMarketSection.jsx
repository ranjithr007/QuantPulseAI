import clsx from "clsx";
import { Activity, BarChart3, ShieldCheck, TrendingUp, Wallet, Waves } from "lucide-react";
import MarketSignalTable from "./MarketSignalTable";
import { deriveExecutorState, enrichRow } from "./MarketSignalTable";
import MetricCard from "./ui/MetricCard";
import MiniCounter from "./ui/MiniCounter";
import Pill from "./ui/Pill";
import { deriveSelectedEligibilityState } from "../utils/eligibility";
import { formatPercent, formatPrice, formatSigned } from "../utils/formatters";
import { getUnifiedMarketState } from "../utils/liveMarket";

export default function LiveMarketSection({
  view,
  auto,
  filters,
  setFilters,
  marketSummary,
  selectedDetail,
  activeTradePlan,
  autoDecision,
  liveStatus,
  watchlist,
  selectedRisk,
  openTrades,
  signalRows,
  paperTradeCandidates,
  onOpenSymbol,
  getSymbolHref,
}) {
  const marketState = getUnifiedMarketState({
    liveStatus,
    liveRecord: selectedDetail.liveMarket,
    freshness: selectedDetail.freshness,
  });
  const selectedLiveState = marketState.liveState;
  const candleState = marketState.candleState;
  const feedConnected = Boolean(liveStatus?.connected);
  const enrichedRows = signalRows.map((row) => enrichRow(row, watchlist, liveStatus, auto?.minConfidence ?? 65));
  const eligibleRows = enrichedRows.filter((row) => row.riskLabel === "Eligible" || row.riskLabel === "Ready to execute");
  const eligibilityState = deriveSelectedEligibilityState({ auto, autoDecision, selectedDetail, selectedRisk, openTrades });
  const feedText = feedConnected
    ? `Binance connected${liveStatus?.cached_count ? ` (${liveStatus.cached_count} cached)` : ""}`
    : liveStatus?.running
      ? liveStatus?.state === "RECONNECTING" ? "Binance reconnecting" : "Binance connecting"
      : "Live feed stopped";
  const filteredRows = enrichedRows.filter((row) => matchesExecutorFilter(row, filters?.executorStatus));
  const selectedExecutor = deriveSelectedExecutorState(selectedDetail, paperTradeCandidates);
  const topEligibleSymbol = eligibleRows[0]?.symbol || "None";

  return (
    <section className="border-b border-white/5 bg-slate-950/55">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="grid items-start gap-3.5 xl:grid-cols-[1.45fr_0.55fr]">
          <div className="self-start rounded-lg border border-white/10 bg-slate-900/80 p-3 shadow-lg shadow-slate-950/20">
            <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="mb-1.5 flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-slate-500">
                  <Activity className="h-4 w-4 text-cyan-300" />
                  Live market dashboard
                </div>
                <h2 className="text-lg font-semibold tracking-tight text-white sm:text-xl">{view.symbol} signal command center</h2>
              </div>

              <div className="flex flex-wrap gap-2">
                <Pill tone={selectedDetail.signalType === "BUY" ? "emerald" : selectedDetail.signalType === "SELL" ? "rose" : "slate"}>
                  {selectedDetail.signalType}
                </Pill>
                <Pill tone={candleState.tone}>
                  {candleState.shortLabel}
                </Pill>
                {selectedDetail.invalidationReason ? <Pill tone="rose">INVALIDATED</Pill> : null}
                <Pill tone={eligibilityState.tone}>{compactEligibilityLabel(eligibilityState.label)}</Pill>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span className={clsx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium", feedConnected ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200" : "border-amber-400/20 bg-amber-500/10 text-amber-200")}>
                <span className={clsx("h-1.5 w-1.5 rounded-full", feedConnected ? "bg-emerald-300" : "bg-amber-300")} />
                {feedText}
              </span>
              {liveStatus?.symbols?.length ? <span>{liveStatus.symbols.length} symbols in feed</span> : null}
            </div>

            <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Current price"
                value={formatPrice(selectedDetail.currentPrice, { fallback: "-", fixedDigits: 2, compactSmall: true })}
                note={
                  selectedLiveState.state !== "FALLBACK"
                    ? marketState.priceSource
                    : candleState.state === "STALE"
                      ? candleState.source
                      : selectedDetail.priceChangePct
                        ? `${formatSigned(selectedDetail.priceChangePct, 2, "-")}% from prior close`
                        : marketState.priceSource
                }
                icon={TrendingUp}
                accent="cyan"
              />
              <MetricCard
                label="Signal confidence"
                value={formatPercent(selectedDetail.confidence, 1, "-")}
                note={selectedDetail.invalidationReason || selectedDetail.signalBias || "Neutral"}
                icon={ShieldCheck}
                accent={selectedDetail.invalidationReason ? "rose" : "emerald"}
              />
              <MetricCard
                label="Risk reward"
                value={formatSigned(activeTradePlan?.risk_reward, 2, "-")}
                note="Trade plan"
                icon={BarChart3}
                accent="amber"
              />
              <MetricCard
                label="Market regime"
                value={selectedDetail.regimeLabel || "WAIT"}
                note={selectedDetail.regimeReason || "No regime summary"}
                icon={Waves}
                accent="rose"
              />
            </div>

            <div className="mt-3 grid gap-2 xl:grid-cols-4">
              <DiagnosticStrip
                label="Live feed"
                value={feedConnected ? "Connected" : "Connecting"}
                note={feedText}
                tone={feedConnected ? "emerald" : "amber"}
              />
              <DiagnosticStrip
                label="Eligibility"
                value={compactEligibilityLabel(eligibilityState.label)}
                note={eligibilityState.note}
                tone={eligibilityState.tone}
              />
              <DiagnosticStrip
                label="Executor truth"
                value={selectedExecutor.label || "Unknown"}
                note={selectedExecutor.note || "No executor summary available"}
                tone={selectedExecutor.tone || "slate"}
              />
              <DiagnosticStrip
                label="Top ready symbol"
                value={topEligibleSymbol}
                note={`${eligibleRows.length} row(s) currently eligible`}
                tone={eligibleRows.length ? "emerald" : "amber"}
              />
            </div>
          </div>

          <div className="grid self-start gap-3.5">
            <div className="rounded-lg border border-white/10 bg-slate-900/80 p-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Market breadth</h3>
                <span className="text-xs text-slate-500">Signals</span>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2.5">
                <MiniCounter label="Buy" value={marketSummary.buyCount} tone="emerald" />
                <MiniCounter label="Sell" value={marketSummary.sellCount} tone="rose" />
                <MiniCounter label="Wait" value={marketSummary.waitCount} tone="slate" />
              </div>
              <div className="mt-3 space-y-2">
                <BreadthBar label="Buy" value={marketSummary.buyCount} total={marketSummary.buyCount + marketSummary.sellCount + marketSummary.waitCount} tone="emerald" />
                <BreadthBar label="Sell" value={marketSummary.sellCount} total={marketSummary.buyCount + marketSummary.sellCount + marketSummary.waitCount} tone="rose" />
                <BreadthBar label="Wait" value={marketSummary.waitCount} total={marketSummary.buyCount + marketSummary.sellCount + marketSummary.waitCount} tone="amber" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">
              <MetricCard label="Ready setups" value={eligibleRows.length} note="Row eligibility" icon={ShieldCheck} accent="emerald" compact />
              <MetricCard label="Executor ready" value={marketSummary.executorReadyCount ?? 0} note="Queued + clear" icon={ShieldCheck} accent="emerald" compact />
              <MetricCard label="Executor blocked" value={marketSummary.executorBlockedCount ?? 0} note="Queued + blocked" icon={Activity} accent="rose" compact />
              <MetricCard label="No queued plan" value={marketSummary.noQueuedPlanCount ?? 0} note="Eligible but not queued" icon={Wallet} accent="amber" compact />
            </div>
          </div>
        </div>

        <div className="mt-3.5">
          <div className="mb-3 flex flex-wrap items-center gap-2.5">
            <label className="grid gap-2">
              <span className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Executor</span>
              <select
                value={filters?.executorStatus || "ALL"}
                onChange={(event) => setFilters?.((current) => ({ ...current, executorStatus: event.target.value }))}
                className="rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-white outline-none transition hover:border-white/20 focus:border-cyan-400/40"
              >
                <option value="ALL">ALL</option>
                <option value="READY">READY</option>
                <option value="BLOCKED">BLOCKED</option>
                <option value="NO_QUEUED_PLAN">NO_QUEUED_PLAN</option>
              </select>
            </label>
          </div>
          <MarketSignalTable
            rows={filteredRows}
            watchlist={watchlist}
            liveStatus={liveStatus}
            paperTradeCandidates={paperTradeCandidates}
            minConfidence={auto?.minConfidence ?? 65}
            activeSymbol={view.symbol}
            onOpenSymbol={onOpenSymbol}
            getSymbolHref={getSymbolHref}
            title="Market scan table"
            subtitle={`Filtered ${filteredRows.length} symbols with live price, AI signal, risk, and executor truth`}
          />
        </div>
      </div>
    </section>
  );
}

function BreadthBar({ label, value, total, tone }) {
  const percent = total > 0 ? Math.round((Number(value) || 0) / total * 100) : 0;
  const toneClass = {
    emerald: "bg-emerald-400 text-emerald-200",
    rose: "bg-rose-400 text-rose-200",
    amber: "bg-amber-400 text-amber-200",
    slate: "bg-slate-500 text-slate-200",
  }[tone] || "bg-cyan-400 text-cyan-200";

  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">
        <span>{label}</span>
        <span className="text-slate-300">{percent}%</span>
      </div>
      <div className="h-2 rounded-full bg-slate-950/90">
        <div className={`h-full rounded-full ${toneClass.split(" ")[0]}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function DiagnosticStrip({ label, value, note, tone = "slate" }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
        <Pill tone={tone}>{value ?? "-"}</Pill>
      </div>
      <div className="mt-1.5 text-xs leading-5 text-slate-400">{note || "-"}</div>
    </div>
  );
}

function compactEligibilityLabel(label) {
  const value = String(label || "");
  if (value === "Ready to execute") return "AUTO READY";
  if (value === "Eligible") return "AUTO ELIGIBLE";
  if (value === "Blocked by confidence") return "CONFIDENCE BLOCK";
  if (value === "Blocked by risk") return "RISK BLOCK";
  if (value === "Auto trading locked") return "AUTO LOCKED";
  if (value === "Emergency stop") return "EMERGENCY STOP";
  return value.toUpperCase() || "AUTO BLOCKED";
}

function matchesExecutorFilter(row, filter) {
  const value = String(filter || "ALL").toUpperCase();
  if (value === "ALL") return true;
  if (value === "READY") return row.executorStatus === "READY";
  if (value === "BLOCKED") return row.executorStatus === "BLOCKED" || row.executorStatus === "STALE";
  if (value === "NO_QUEUED_PLAN") return row.executorStatus === "NO_QUEUED_PLAN";
  return true;
}

function deriveSelectedExecutorState(detail, candidates = []) {
  return deriveExecutorState(
    {
      symbol: detail?.symbol,
      type: detail?.signalType,
    },
    candidates
  );
}
