import clsx from "clsx";
import { Activity, BarChart3, ShieldCheck, TrendingUp, Wallet, Waves } from "lucide-react";
import MarketSignalTable from "./MarketSignalTable";
import MetricCard from "./ui/MetricCard";
import MiniCounter from "./ui/MiniCounter";
import Pill from "./ui/Pill";
import { formatPercent, formatPrice, formatSigned } from "../utils/formatters";
import { getLiveMarketState } from "../utils/liveMarket";

export default function LiveMarketSection({
  view,
  marketSummary,
  selectedDetail,
  activeTradePlan,
  autoDecision,
  liveStatus,
  watchlist,
  openTrades,
  signalRows,
  onOpenSymbol,
  getSymbolHref,
}) {
  const liveRecord = selectedDetail.liveMarket;
  const selectedLiveState = getLiveMarketState({
    liveStatus,
    updatedAt: liveRecord?.received_at || liveRecord?.event_time,
    hasLiveRecord: Boolean(liveRecord),
  });
  const feedConnected = Boolean(liveStatus?.connected);
  const feedText = feedConnected
    ? `Binance connected${liveStatus?.cached_count ? ` (${liveStatus.cached_count} cached)` : ""}`
    : liveStatus?.running
      ? liveStatus?.state === "RECONNECTING" ? "Binance reconnecting" : "Binance connecting"
      : "Live feed stopped";

  return (
    <section className="border-b border-white/5 bg-slate-950/55">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="grid gap-3.5 xl:grid-cols-[1.45fr_0.55fr]">
          <div className="rounded-lg border border-white/10 bg-slate-900/80 p-3 shadow-lg shadow-slate-950/20">
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
                <Pill tone={selectedDetail.freshness?.is_stale ? "amber" : "emerald"}>
                  {selectedDetail.freshness?.is_stale ? "STALE" : "FRESH"}
                </Pill>
                {selectedDetail.invalidationReason ? <Pill tone="rose">INVALIDATED</Pill> : null}
                <Pill tone={autoDecision.allowed ? "emerald" : "rose"}>{autoDecision.allowed ? "AUTO READY" : "AUTO BLOCKED"}</Pill>
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
                    ? selectedLiveState.source
                    : selectedDetail.freshness?.is_stale
                      ? "Stale market candle"
                      : selectedDetail.priceChangePct
                        ? `${formatSigned(selectedDetail.priceChangePct, 2, "-")}% from prior close`
                        : selectedLiveState.source
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
          </div>

          <div className="grid gap-3.5">
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

            <div className="grid grid-cols-2 gap-2.5">
              <MetricCard label="Ready setups" value={watchlist?.summary?.ready ?? 0} note="Watchlist" icon={ShieldCheck} accent="emerald" compact />
              <MetricCard label="Open trades" value={openTrades.length} note="Paper trading" icon={Wallet} accent="cyan" compact />
            </div>
          </div>
        </div>

        <div className="mt-3.5">
          <MarketSignalTable
            rows={signalRows}
            watchlist={watchlist}
            liveStatus={liveStatus}
            activeSymbol={view.symbol}
            onOpenSymbol={onOpenSymbol}
            getSymbolHref={getSymbolHref}
            title="Market scan table"
            subtitle="Live price, AI-calculated signal, RS, stage, regime, bias, and risk"
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
