import clsx from "clsx";
import {
    Activity,
    BarChart3,
    Bot,
    Eye,
    RadioTower,
    ShieldCheck,
    Target,
    TrendingDown,
    TrendingUp,
    Waves,
} from "lucide-react";
import AdvancedTradingViewPanel from "../components/signal-details/AdvancedTradingViewPanel";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { formatNumber, formatPercent, formatPrice, formatSigned } from "../utils/formatters";
import { progressToneClass } from "../utils/toneClasses";

export default function DashboardHomePage({
    view,
    marketSummary,
    selectedDetail,
    activeTradePlan,
    autoDecision,
    liveStatus,
    watchlist,
    openTrades,
    signalRows,
    candleSeries,
    selectedRisk,
    onOpenSymbol,
}) {
    const rotation = rotationSignal(watchlist, marketSummary);
    const longPct = normalizeProbability(selectedDetail.longSidePct);
    const shortPct = normalizeProbability(selectedDetail.shortSidePct);
    const funding = fundingSnapshot(selectedDetail, activeTradePlan);
    const chartPrice = resolveChartPrice(selectedDetail.currentPrice, view.symbol, signalRows);
    const topSignals = [...signalRows]
        .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))
        .slice(0, 6);

    return (
        <section className="border-b border-white/5 bg-slate-950/55">
            <div className="mx-auto grid w-full max-w-[1680px] gap-3.5 px-4 py-4 sm:px-6 lg:px-8">
                <div className="grid gap-3.5 xl:grid-cols-[1.15fr_0.85fr]">
                    <div className="rounded-lg border border-white/10 bg-slate-900/75 p-3.5">
                        <div className="flex flex-col gap-2.5 lg:flex-row lg:items-start lg:justify-between">
                            <div>
                                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
                                    <Activity className="h-4 w-4 text-cyan-300" />
                                    Dashboard Home
                                </div>
                                <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">
                                    {view.symbol} dashboard
                                </h2>
                                <div className="mt-1 text-xs text-slate-500">
                                    Live feed, AI bias, and risk gate in one view
                                </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <Pill tone={selectedDetail.regimeTone}>{selectedDetail.regimeLabel || "WAIT"}</Pill>
                                <Pill tone={selectedDetail.signalType === "BUY" ? "emerald" : selectedDetail.signalType === "SELL" ? "rose" : "slate"}>
                                    {selectedDetail.signalType}
                                </Pill>
                                <Pill tone={autoDecision.allowed ? "emerald" : "rose"}>
                                    {autoDecision.allowed ? "AUTO ELIGIBLE" : "AUTO BLOCKED"}
                                </Pill>
                            </div>
                        </div>

                        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                            <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                                <MetricCard
                                    label="Market regime"
                                    value={selectedDetail.regimeLabel || "WAIT"}
                                    note={selectedDetail.regimeReason || "No regime summary"}
                                    icon={Waves}
                                    accent={selectedDetail.regimeTone || "cyan"}
                                    compact
                                />
                                <MetricCard
                                    label="Crypto rotation"
                                    value={rotation.label}
                                    note={rotation.note}
                                    icon={RadioTower}
                                    accent={rotation.tone}
                                    compact
                                />
                                <MetricCard
                                    label="Long / short bias"
                                    value={`${formatPercent(longPct, 0)} / ${formatPercent(shortPct, 0)}`}
                                    note="Probability engine"
                                    icon={BarChart3}
                                    accent={longPct >= shortPct ? "emerald" : "rose"}
                                    compact
                                />
                            </div>
                            <MetricCard
                                label="Risk gate"
                                value={riskGateLabel(selectedRisk, autoDecision)}
                                note={autoDecision.reason || selectedRisk?.status || "Risk engine"}
                                icon={ShieldCheck}
                                accent={autoDecision.allowed ? "emerald" : "rose"}
                                compact
                            />
                        </div>

                        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                            <PulseCard
                                label="Live source"
                                value={liveStatus?.running ? "Live feed" : "Cache mode"}
                                note={
                                    liveStatus?.running
                                        ? `${liveStatus?.cached_count ?? 0} cached symbols`
                                        : "Starting live feed"
                                }
                                icon={RadioTower}
                                tone={liveStatus?.running ? "emerald" : "amber"}
                            />
                            <PulseCard
                                label="AI confidence"
                                value={formatPercent(selectedDetail.confidence, 0, "-")}
                                note="Calculated"
                                icon={Bot}
                                tone={selectedDetail.confidence >= 70 ? "emerald" : "amber"}
                            />
                            <PulseCard
                                label="Ready setups"
                                value={watchlist?.summary?.ready ?? 0}
                                note={`Universe ${watchlist?.summary?.total ?? signalRows.length}`}
                                icon={ShieldCheck}
                                tone="cyan"
                            />
                            <PulseCard
                                label="Open trades"
                                value={openTrades.length}
                                note={autoDecision.allowed ? "Auto eligible" : "Auto blocked"}
                                icon={BarChart3}
                                tone={autoDecision.allowed ? "emerald" : "rose"}
                            />
                        </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
                        <BiasPanel longPct={longPct} shortPct={shortPct} selectedDetail={selectedDetail} activeTradePlan={activeTradePlan} />
                        <AutomationPanel autoDecision={autoDecision} selectedRisk={selectedRisk} openTrades={openTrades} />
                    </div>
                </div>

                <div>
                    <AdvancedTradingViewPanel
                        currentPrice={chartPrice}
                        symbol={view.symbol}
                        timeframe={view.timeframe}
                        tradePlan={activeTradePlan || selectedDetail.tradePlan}
                        resistanceLevels={selectedDetail.resistanceLevels}
                        supportLevels={selectedDetail.supportLevels}
                    />
                </div>

                <div className="grid gap-3 xl:grid-cols-[1.35fr_0.65fr]">
                    <SignalScreener rows={topSignals} activeSymbol={view.symbol} onOpenSymbol={onOpenSymbol} />
                    <MicrostructurePanel selectedDetail={selectedDetail} funding={funding} />
                </div>
            </div>
        </section>
    );
}

function BiasPanel({ longPct, shortPct, selectedDetail, activeTradePlan }) {
    const dominant = longPct >= shortPct ? "LONG BIAS" : "SHORT BIAS";
    const biasGap = Math.abs(longPct - shortPct);
    const riskReward = activeTradePlan?.risk_reward ?? selectedDetail.tradePlan?.risk_reward;

    return (
        <div className="rounded-lg border border-white/10 bg-slate-900/75 p-3">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <div className="text-sm font-semibold text-white">Directional bias</div>
                    <div className="mt-0.5 line-clamp-2 max-w-[28rem] text-xs leading-4 text-slate-500">
                        {selectedDetail.regimeReason || "Regime context pending"}
                    </div>
                </div>
                <Pill tone={longPct >= shortPct ? "emerald" : "rose"}>{dominant}</Pill>
            </div>

            <div className="mt-3 space-y-2">
                <BiasMeter label="Long" value={longPct} tone="emerald" />
                <BiasMeter label="Short" value={shortPct} tone="rose" />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 xl:grid-cols-4">
                <CompactStat label="Long" value={formatPercent(longPct, 0, "-")} tone="emerald" />
                <CompactStat label="Short" value={formatPercent(shortPct, 0, "-")} tone="rose" />
                <CompactStat label="Gap" value={formatPercent(biasGap, 0, "-")} tone={biasGap >= 25 ? "cyan" : "slate"} />
                <CompactStat label="Confidence" value={formatPercent(selectedDetail.confidence, 0, "-")} tone={selectedDetail.confidence >= 70 ? "emerald" : "amber"} />
                <CompactStat label="RR" value={formatSigned(riskReward, 2, "-")} tone={Number(riskReward || 0) >= 1.5 ? "emerald" : "amber"} />
                <CompactStat label="Regime" value={selectedDetail.regimeLabel || "WAIT"} tone="cyan" />
            </div>
        </div>
    );
}

function AutomationPanel({ autoDecision, selectedRisk, openTrades }) {
    const blockedReasons = autoDecision.reasons?.length ? autoDecision.reasons.slice(0, 3) : ["No blocking reason"];
    const riskTone = selectedRisk?.is_usable === false ? "rose" : selectedRisk?.decision === "APPROVE" ? "emerald" : "cyan";

    return (
        <div className="rounded-lg border border-white/10 bg-slate-900/75 p-3">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <div className="text-sm font-semibold text-white">Risk and auto-trading</div>
                    <div className="mt-0.5 line-clamp-2 max-w-[34rem] text-xs leading-4 text-slate-500">
                        {autoDecision.reason || selectedRisk?.status || "Eligibility, blocks, exposure"}
                    </div>
                </div>
                <Pill tone={autoDecision.allowed ? "emerald" : "rose"}>{autoDecision.allowed ? "Eligible" : "Blocked"}</Pill>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <StatusTile label="Open trades" value={openTrades.length} icon={Bot} />
                <StatusTile label="Risk decision" value={selectedRisk?.decision || selectedRisk?.status || "WAIT"} icon={ShieldCheck} tone={riskTone} />
                <StatusTile label="Risk %" value={formatPercent(selectedRisk?.risk_percent, 1, "-")} icon={Target} tone="cyan" />
                <StatusTile label="Position" value={formatNumber(selectedRisk?.position_size, 2, "-")} icon={BarChart3} tone={riskTone} />
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
                {blockedReasons.map((reason) => (
                    <div key={reason} className="rounded-lg border border-white/10 bg-slate-950/65 px-2.5 py-1.5 text-[11px] font-medium text-slate-300">
                        {reason}
                    </div>
                ))}
            </div>
        </div>
    );
}

function BiasMeter({ label, value, tone }) {
    return (
        <div>
            <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                <span className="font-medium text-slate-300">{label}</span>
                <span className="font-semibold text-white">{formatPercent(value, 0, "-")}</span>
            </div>
            <div className="h-2 rounded-full bg-slate-950">
                <div className={clsx("h-full rounded-full", progressToneClass(tone))} style={{ width: `${Math.max(0, Math.min(value, 100))}%` }} />
            </div>
        </div>
    );
}

function CompactStat({ label, value, tone = "slate" }) {
    const toneClass = {
        emerald: "text-emerald-200",
        rose: "text-rose-200",
        amber: "text-amber-200",
        cyan: "text-cyan-200",
        slate: "text-slate-100",
    }[tone];

    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/65 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
            <div className={clsx("mt-1 truncate text-sm font-semibold", toneClass)}>{value}</div>
        </div>
    );
}

function SignalScreener({ rows, activeSymbol, onOpenSymbol }) {
    return (
        <div className="overflow-hidden rounded-lg border border-white/10 bg-slate-900/75">
            <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
                <div>
                    <div className="text-sm font-semibold text-white">Signal screener</div>
                    <div className="text-xs text-slate-500">Ranked by confidence</div>
                </div>
                <Pill tone="cyan">{rows.length} tracked</Pill>
            </div>
            <div className="overflow-x-auto">
                <table className="min-w-[760px] divide-y divide-white/5 text-left text-sm">
                    <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                        <tr>
                            <th className="px-3 py-2">Symbol</th>
                            <th className="px-3 py-2">Signal</th>
                            <th className="px-3 py-2">Confidence</th>
                            <th className="px-3 py-2">Price</th>
                            <th className="px-3 py-2">Details</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                        {rows.map((row) => (
                            <tr key={row.symbol} className={clsx("transition", activeSymbol === row.symbol && "bg-cyan-500/10")}>
                                <td className="px-3 py-2 font-medium text-white">{row.symbol}</td>
                                <td className="px-3 py-2">
                                    <Pill tone={row.type === "BUY" ? "emerald" : row.type === "SELL" ? "rose" : "slate"}>{row.type}</Pill>
                                </td>
                                <td className="px-3 py-2 text-slate-300">{formatPercent(row.confidence, 0)}</td>
                                <td className="px-3 py-2 text-slate-300">{formatPrice(row.currentPrice, { fallback: "-", compactSmall: true })}</td>
                                <td className="px-3 py-2">
                                    <button
                                        type="button"
                                        onClick={() => onOpenSymbol(row.symbol)}
                                        className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-slate-950/70 px-3 py-1.5 text-xs font-medium text-cyan-200 transition hover:border-cyan-400/40 hover:bg-cyan-500/10"
                                    >
                                        <Eye className="h-3.5 w-3.5" />
                                        View Details
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function MicrostructurePanel({ selectedDetail, funding }) {
    const whaleBuyPct = Math.round((selectedDetail.whaleBuyVolume / selectedDetail.whaleMaxVolume) * 100);
    const whaleSellPct = Math.round((selectedDetail.whaleSellVolume / selectedDetail.whaleMaxVolume) * 100);

    return (
        <div className="rounded-lg border border-white/10 bg-slate-900/75 p-3.5">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <div className="text-sm font-semibold text-white">Orderflow, whale, funding</div>
                    <div className="text-xs text-slate-500">Microstructure context</div>
                </div>
                <Pill tone={selectedDetail.orderflowTone}>{selectedDetail.orderflowBadge || "FLOW"}</Pill>
            </div>

            <div className="mt-3.5 grid gap-3">
                <FlowLine label="Orderflow delta" value={formatNumber(flowDelta(selectedDetail), 2, "-")} tone={selectedDetail.orderflowTone} icon={Activity} />
                <FlowLine label="Whale buy volume" value={formatNumber(selectedDetail.whaleBuyVolume, 0, "-")} tone="emerald" icon={TrendingUp} progress={whaleBuyPct} />
                <FlowLine label="Whale sell volume" value={formatNumber(selectedDetail.whaleSellVolume, 0, "-")} tone="rose" icon={TrendingDown} progress={whaleSellPct} />
                <FlowLine label="Funding pressure" value={funding.label} tone={funding.tone} icon={Target} />
            </div>
        </div>
    );
}

function FlowLine({ label, value, tone = "slate", icon: Icon, progress }) {
    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/65 p-3">
            <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                    <Icon className="h-4 w-4 text-slate-500" />
                    <span className="truncate text-sm text-slate-300">{label}</span>
                </div>
                <span className="text-sm font-medium text-white">{value}</span>
            </div>
            {typeof progress === "number" ? (
                <div className="mt-3 h-1.5 rounded-full bg-slate-800">
                    <div className={clsx("h-full rounded-full", progressToneClass(tone))} style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }} />
                </div>
            ) : null}
        </div>
    );
}

function StatusTile({ label, value, icon: Icon, tone = "slate" }) {
    const toneClass = {
        emerald: "text-emerald-200",
        rose: "text-rose-200",
        amber: "text-amber-200",
        cyan: "text-cyan-200",
        slate: "text-white",
    }[tone];

    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/65 p-2.5">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                <Icon className="h-3.5 w-3.5" />
                {label}
            </div>
            <div className={clsx("mt-1.5 truncate text-sm font-semibold", toneClass)}>{value}</div>
        </div>
    );
}

function PulseCard({ label, value, note, icon: Icon, tone }) {
    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/55 px-3 py-2.5">
            <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
                    <div className="mt-1 truncate text-sm font-semibold text-white">{value}</div>
                    <div className="mt-0.5 text-[11px] text-slate-400">{note}</div>
                </div>
                <div className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-lg border", pulseToneClass(tone))}>
                    <Icon className="h-3.5 w-3.5" />
                </div>
            </div>
        </div>
    );
}

function pulseToneClass(tone) {
    return {
        emerald: "border-emerald-400/20 bg-emerald-500/10 text-emerald-200",
        rose: "border-rose-400/20 bg-rose-500/10 text-rose-200",
        amber: "border-amber-400/20 bg-amber-500/10 text-amber-200",
        cyan: "border-cyan-400/20 bg-cyan-500/10 text-cyan-200",
    }[tone || "cyan"];
}

function rotationSignal(watchlist, marketSummary) {
    const ready = Number(watchlist?.summary?.ready || 0);
    const long = Number(watchlist?.summary?.long || marketSummary?.buyCount || 0);
    const short = Number(watchlist?.summary?.short || marketSummary?.sellCount || 0);

    if (ready === 0) return { label: "Defensive", note: "No ready setups", tone: "amber" };
    if (long > short) return { label: "Risk-on", note: `${long} long setups leading`, tone: "emerald" };
    if (short > long) return { label: "Risk-off", note: `${short} short setups leading`, tone: "rose" };
    return { label: "Balanced", note: `${ready} ready setups`, tone: "cyan" };
}

function fundingSnapshot(selectedDetail, activeTradePlan) {
    const fundingRate = Number(selectedDetail?.derivatives?.latest_funding_rate);
    const openInterestChange = Number(selectedDetail?.derivatives?.latest_open_interest_change_pct);
    const rr = Number(activeTradePlan?.risk_reward ?? selectedDetail.tradePlan?.risk_reward ?? 0);
    const longPct = normalizeProbability(selectedDetail.longSidePct);
    const shortPct = normalizeProbability(selectedDetail.shortSidePct);

    if (Number.isFinite(fundingRate) || Number.isFinite(openInterestChange)) {
        if (fundingRate > 0 && openInterestChange > 0) return { label: "Longs paying, OI rising", tone: "rose" };
        if (fundingRate < 0 && openInterestChange > 0) return { label: "Shorts paying, OI rising", tone: "emerald" };
        if (fundingRate > 0) return { label: "Positive funding", tone: "amber" };
        if (fundingRate < 0) return { label: "Negative funding", tone: "cyan" };
    }

    if (longPct > shortPct + 15 && rr >= 1.5) return { label: "Long supportive", tone: "emerald" };
    if (shortPct > longPct + 15 && rr >= 1.5) return { label: "Short supportive", tone: "rose" };
    if (rr > 0 && rr < 1.2) return { label: "Risk premium weak", tone: "amber" };
    return { label: "Neutral carry", tone: "cyan" };
}

function riskGateLabel(selectedRisk, autoDecision) {
    if (autoDecision.allowed) return "Eligible";
    if (selectedRisk?.is_usable === false) return "Blocked by risk";
    if (autoDecision.reasons?.some((reason) => String(reason).toLowerCase().includes("confidence"))) return "Blocked by confidence";
    return "Blocked";
}

function normalizeProbability(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return number <= 1 ? number * 100 : number;
}

function flowDelta(selectedDetail) {
    const record = selectedDetail.selectedOrderflow || {};
    return record.delta ?? record.Delta ?? record.cumulative_delta ?? record.CVD ?? 0;
}

function resolveChartPrice(currentPrice, symbol, signalRows) {
    const direct = Number(currentPrice);
    if (Number.isFinite(direct) && direct > 0) return direct;

    const rowPrice = Number(signalRows.find((row) => row.symbol === symbol)?.currentPrice);
    if (Number.isFinite(rowPrice) && rowPrice > 0) return rowPrice;

    const defaults = {
        BTCUSDT: 66515.99,
        ETHUSDT: 1773.3,
        XRPUSDT: 1.2362,
        SOLUSDT: 74.54,
        BNBUSDT: 613.39,
        DOGEUSDT: 0.1335,
    };

    return defaults[symbol] || 100;
}
