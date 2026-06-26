import clsx from "clsx";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Brain,
  Layers3,
  RadioTower,
  ShieldCheck,
  Target,
} from "lucide-react";
import AdvancedTradingViewPanel from "./signal-details/AdvancedTradingViewPanel";
import InfoLine from "./signal-details/InfoLine";
import ProgressLine from "./signal-details/ProgressLine";
import SignalQualityPanel from "./signal-details/SignalQualityPanel";
import VolumePanel from "./signal-details/VolumePanel";
import Pill from "./ui/Pill";
import {
  formatNumber,
  formatPercent,
  formatPrice,
  formatSigned,
  formatTargets,
  safeNumber,
  tooltipStyle,
} from "../utils/formatters";
import { getLiveMarketState } from "../utils/liveMarket";

export default function SignalDetailsSection({
  view,
  selectedDetail,
  activeTradePlan,
  candleSeries,
  volumeSeries,
  selectedRisk,
  liveStatus,
}) {
  const chartPrice = resolveChartPrice(selectedDetail.currentPrice, view.symbol);
  const tradePlan = activeTradePlan || selectedDetail.tradePlan || {};
  const riskState = riskApprovalState(selectedRisk, selectedDetail);
  const fundingOi = fundingOiSnapshot(selectedDetail);
  const liveRecord = selectedDetail.liveMarket;
  const selectedLiveState = getLiveMarketState({
    liveStatus,
    updatedAt: liveRecord?.received_at || liveRecord?.event_time,
    hasLiveRecord: Boolean(liveRecord),
  });
  const feedConnected = Boolean(liveStatus?.connected);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-1.5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Coin Intelligence</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">{view.symbol} intelligence</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill tone={selectedDetail.signalType === "BUY" ? "emerald" : selectedDetail.signalType === "SELL" ? "rose" : "slate"}>
              {selectedDetail.signalType}
            </Pill>
            <Pill tone={selectedDetail.regimeTone}>{selectedDetail.regimeLabel || "WAIT"}</Pill>
            <Pill tone={riskState.tone}>{riskState.label}</Pill>
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className={clsx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium", feedConnected ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200" : "border-amber-400/20 bg-amber-500/10 text-amber-200")}>
            <span className={clsx("h-1.5 w-1.5 rounded-full", feedConnected ? "bg-emerald-300" : "bg-amber-300")} />
            {feedConnected ? `Live connected${liveStatus?.cached_count ? ` (${liveStatus.cached_count} cached)` : ""}` : liveStatus?.running ? "Binance reconnecting" : "Live feed stopped"}
          </span>
          {liveStatus?.symbols?.length ? <span>{liveStatus.symbols.length} symbols streaming</span> : null}
        </div>

        <div className="mt-3.5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <DecisionMetric
            label="Live price"
            value={formatPrice(chartPrice, { fallback: "-", compactSmall: true })}
            note={selectedLiveState.source}
            icon={RadioTower}
            tone="cyan"
          />
          <DecisionMetric
            label="AI confidence"
            value={formatPercent(selectedDetail.confidence, 0, "-")}
            note={selectedDetail.invalidationReason || selectedDetail.signalBias || "AI calculated"}
            icon={Brain}
            tone={selectedDetail.invalidationReason ? "rose" : "emerald"}
          />
          <DecisionMetric
            label="Risk reward"
            value={formatSigned(tradePlan?.risk_reward, 2, "-")}
            note="Entry plan"
            icon={Target}
            tone={safeNumber(tradePlan?.risk_reward, 0) >= 1.5 ? "emerald" : "amber"}
          />
          <DecisionMetric
            label="Risk approval"
            value={riskState.label}
            note={riskState.note}
            icon={ShieldCheck}
            tone={riskState.tone}
          />
        </div>

        <div className="mt-3 grid gap-3 2xl:grid-cols-[minmax(0,1.45fr)_minmax(340px,0.55fr)]">
          <div className="min-w-0 space-y-3">
            <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-medium text-white">Price action and execution levels</div>
                  <div className="text-xs text-slate-500">{view.timeframe} candles, risk levels, support, and resistance</div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Pill tone="cyan">{formatPrice(chartPrice, { fallback: "-", compactSmall: true })}</Pill>
                  <Pill tone={selectedDetail.freshness?.is_stale ? "amber" : "emerald"}>
                    {selectedDetail.freshness?.is_stale ? "STALE CANDLE" : "FRESH CANDLE"}
                  </Pill>
                </div>
              </div>

              <div className="mb-2 grid gap-2 sm:grid-cols-4">
                <CompactValue label="Entry" value={formatPrice(tradePlan?.entry)} tone="cyan" />
                <CompactValue label="Stop" value={formatPrice(tradePlan?.stop_loss)} tone="rose" />
                <CompactValue label="Target 1" value={formatPrice(tradePlan?.target1)} tone="emerald" />
                <CompactValue label="RR" value={formatSigned(tradePlan?.risk_reward, 2, "-")} tone={safeNumber(tradePlan?.risk_reward, 0) >= 1.5 ? "emerald" : "amber"} />
              </div>

              <AdvancedTradingViewPanel
                currentPrice={chartPrice}
                resistanceLevels={selectedDetail.resistanceLevels}
                supportLevels={selectedDetail.supportLevels}
                tradePlan={tradePlan}
                timeframe={view.timeframe}
                symbol={view.symbol}
                height={380}
                embedded
              />
            </div>

            <div className="grid gap-2.5 xl:grid-cols-[0.9fr_1.1fr]">
              <TradePlanPanel tradePlan={tradePlan} selectedDetail={selectedDetail} />
              <LevelPanel selectedDetail={selectedDetail} />
            </div>

            <div className="grid gap-2.5 xl:grid-cols-2">
              <VolumePanel volumeSeries={volumeSeries} />
              <SignalQualityPanel breakdown={selectedDetail.breakdown || []} />
            </div>
          </div>

          <aside className="grid min-w-0 gap-3 2xl:grid-cols-2">
            <SidebarGroup title="Risk control" subtitle="Eligibility, blocks, and sizing" className="2xl:col-span-2">
              <RiskApprovalPanel selectedRisk={selectedRisk} riskState={riskState} selectedDetail={selectedDetail} />
              <AiReasonPanel selectedDetail={selectedDetail} selectedRisk={selectedRisk} />
            </SidebarGroup>

            <SidebarGroup title="Order flow" subtitle="Execution and participation" className="2xl:col-span-2">
              <OrderflowPanel selectedDetail={selectedDetail} />
              <WhalePanel selectedDetail={selectedDetail} />
            </SidebarGroup>

            <SidebarGroup title="Derivatives" subtitle="Liquidation and funding context" className="2xl:col-span-2">
              <LiquidationPanel selectedDetail={selectedDetail} chartPrice={chartPrice} />
              <FundingOiPanel fundingOi={fundingOi} />
            </SidebarGroup>
          </aside>
        </div>
      </div>
    </section>
  );
}

function DecisionMetric({ label, value, note, icon: Icon, tone }) {
  const toneClass = {
    emerald: "border-emerald-400/20 bg-emerald-500/10 text-emerald-200",
    rose: "border-rose-400/20 bg-rose-500/10 text-rose-200",
    amber: "border-amber-400/20 bg-amber-500/10 text-amber-200",
    cyan: "border-cyan-400/20 bg-cyan-500/10 text-cyan-200",
  }[tone || "cyan"];

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
          <div className="mt-1.5 truncate text-lg font-semibold tracking-tight text-white">{value}</div>
          <div className="mt-1 line-clamp-1 text-xs leading-5 text-slate-400">{note}</div>
        </div>
        <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border ${toneClass}`}>
          <Icon className="h-4 w-4" />
        </div>
      </div>
    </div>
  );
}

function CompactValue({ label, value, tone = "slate" }) {
  const toneClass = {
    emerald: "text-emerald-200",
    rose: "text-rose-200",
    amber: "text-amber-200",
    cyan: "text-cyan-200",
    slate: "text-white",
  }[tone];

  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className={`mt-1 truncate text-sm font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function TradePlanPanel({ tradePlan, selectedDetail }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Entry plan</div>
          <div className="text-xs text-slate-500">AI levels and risk markers</div>
        </div>
        <Pill tone={selectedDetail.signalType === "BUY" ? "emerald" : selectedDetail.signalType === "SELL" ? "rose" : "slate"}>
          {selectedDetail.signalType}
        </Pill>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <CompactValue label="Entry" value={formatPrice(tradePlan?.entry)} tone="cyan" />
        <CompactValue label="Stop loss" value={formatPrice(tradePlan?.stop_loss)} tone="rose" />
        <CompactValue label="Target 1" value={formatPrice(tradePlan?.target1)} tone="emerald" />
        <CompactValue label="Target 2" value={formatPrice(tradePlan?.target2)} tone="emerald" />
        <CompactValue label="Target 3" value={formatPrice(tradePlan?.target3)} tone="emerald" />
        <CompactValue label="Targets" value={formatTargets(tradePlan)} tone="slate" />
      </div>
    </div>
  );
}

function LevelPanel({ selectedDetail }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Support and resistance</div>
          <div className="text-xs text-slate-500">ATR and recent candle-derived levels</div>
        </div>
        <Layers3 className="h-4 w-4 text-slate-500" />
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <CompactValue label="Resistance 1" value={formatPrice(selectedDetail.resistanceLevels?.r1)} tone="cyan" />
        <CompactValue label="Resistance 2" value={formatPrice(selectedDetail.resistanceLevels?.r2)} tone="cyan" />
        <CompactValue label="Resistance 3" value={formatPrice(selectedDetail.resistanceLevels?.r3)} tone="cyan" />
        <CompactValue label="Support 1" value={formatPrice(selectedDetail.supportLevels?.s1)} tone="amber" />
        <CompactValue label="Support 2" value={formatPrice(selectedDetail.supportLevels?.s2)} tone="amber" />
        <CompactValue label="Support 3" value={formatPrice(selectedDetail.supportLevels?.s3)} tone="amber" />
        <CompactValue label="Long probability" value={formatPercent(normalizeProbability(selectedDetail.longSidePct), 0)} tone="emerald" />
        <CompactValue label="Short probability" value={formatPercent(normalizeProbability(selectedDetail.shortSidePct), 0)} tone="rose" />
      </div>
    </div>
  );
}

function RiskApprovalPanel({ selectedRisk, riskState, selectedDetail }) {
  const messages = riskMessages(selectedRisk, selectedDetail);

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Risk approval</h3>
        <Pill tone={riskState.tone}>{riskState.label}</Pill>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <CompactValue label="Risk %" value={formatPercent(selectedRisk?.risk_percent, 1, "-")} tone="cyan" />
        <CompactValue label="Position" value={formatNumber(selectedRisk?.position_size, 2, "-")} tone={riskState.tone} />
      </div>
      <div className="mt-3 space-y-2">
        {messages.map((message) => (
          <InfoLine key={message.label} label={message.label} value={message.value} />
        ))}
      </div>
    </div>
  );
}

function AiReasonPanel({ selectedDetail, selectedRisk }) {
  const reasons = [
    { label: "Regime", value: selectedDetail.regimeReason || "No regime explanation" },
    {
      label: "Setup",
      value: selectedDetail.tradeSetup?.setup?.reason || selectedDetail.tradeSetup?.trigger?.reason || "Unavailable",
    },
    { label: "Trigger", value: selectedDetail.entryTrigger?.trigger?.reason || "Unavailable" },
    { label: "Risk", value: selectedRisk?.decision || selectedRisk?.status || "No risk decision" },
  ];

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">AI reasons</h3>
        <Brain className="h-4 w-4 text-cyan-300" />
      </div>
      <div className="space-y-2">
        {reasons.map((reason) => (
          <InfoLine key={reason.label} label={reason.label} value={reason.value} />
        ))}
      </div>
    </div>
  );
}

function OrderflowPanel({ selectedDetail }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Orderflow</h3>
        <Pill tone={selectedDetail.orderflowTone}>{selectedDetail.orderflowBadge || "FLOW"}</Pill>
      </div>
      <div className="space-y-2">
        {(selectedDetail.orderflowLines || []).map((item) => (
          <InfoLine key={item.label} label={item.label} value={item.value} />
        ))}
        <InfoLine label="Delta source" value={selectedDetail.selectedOrderflow ? "Orderflow engine" : "Unavailable"} />
      </div>
    </div>
  );
}

function WhalePanel({ selectedDetail }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Whale activity</h3>
        <Pill tone={selectedDetail.whaleTone}>{selectedDetail.whaleTone === "emerald" ? "BUYERS" : "SELLERS"}</Pill>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <CompactValue label="Buy count" value={selectedDetail.whaleBuyCount} tone="emerald" />
        <CompactValue label="Sell count" value={selectedDetail.whaleSellCount} tone="rose" />
      </div>
      <div className="mt-3">
        <ProgressLine label="Buy volume" value={selectedDetail.whaleBuyVolume} max={selectedDetail.whaleMaxVolume} tone="emerald" />
        <ProgressLine label="Sell volume" value={selectedDetail.whaleSellVolume} max={selectedDetail.whaleMaxVolume} tone="rose" />
      </div>
    </div>
  );
}

function LiquidationPanel({ selectedDetail, chartPrice }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Liquidations</h3>
        <Pill tone="amber">Estimated</Pill>
      </div>
      <div className="space-y-2">
        <InfoLine label="Upper zone" value={formatPrice(selectedDetail.liquidationZones?.upper)} />
        <InfoLine label="Lower zone" value={formatPrice(selectedDetail.liquidationZones?.lower)} />
        <InfoLine label="Anchor" value={formatPrice(chartPrice)} />
      </div>
    </div>
  );
}

function FundingOiPanel({ fundingOi }) {
  const fundingHistory = fundingOi.fundingHistory || [];
  const openInterestHistory = fundingOi.openInterestHistory || [];

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Funding / OI</h3>
        <Pill tone={fundingOi.tone}>{fundingOi.bias}</Pill>
      </div>
      <div className="space-y-2">
        <InfoLine label="Funding" value={fundingOi.funding} />
        <InfoLine label="Open interest" value={fundingOi.openInterest} />
        <InfoLine label="Interpretation" value={fundingOi.note} />
      </div>
      <div className="mt-3 grid gap-2 xl:grid-cols-2">
        <DerivativeMiniChart
          title="Funding rate"
          data={fundingHistory}
          dataKey="value"
          color="#38bdf8"
          valueFormatter={(value) => formatPercent(value, 4, "-")}
        />
        <DerivativeMiniChart
          title="Open interest"
          data={openInterestHistory}
          dataKey="value"
          color="#34d399"
          valueFormatter={(value) => formatOpenInterest(value)}
        />
      </div>
    </div>
  );
}

function DerivativeMiniChart({ title, data, dataKey, color, valueFormatter }) {
  if (!Array.isArray(data) || data.length < 2) {
    return (
      <div className="rounded-lg border border-white/10 bg-slate-950/65 p-2.5">
        <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{title}</div>
        <div className="mt-2 text-xs text-slate-400">Not enough history yet</div>
      </div>
    );
  }

  const chartId = `gradient-${String(title).toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/65 p-2.5">
      <div className="mb-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">{title}</div>
      <div className="h-28 w-full min-w-0">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <AreaChart data={data}>
            <defs>
              <linearGradient id={chartId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.35} />
                <stop offset="95%" stopColor={color} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 10 }} />
            <YAxis
              tickLine={false}
              axisLine={false}
              tick={{ fill: "#64748b", fontSize: 10 }}
              tickFormatter={(value) => compactDerivativeTick(value)}
              width={56}
            />
            <Tooltip
              contentStyle={tooltipStyle()}
              formatter={(value) => valueFormatter(value)}
            />
            <Area
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              fillOpacity={1}
              fill={`url(#${chartId})`}
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function SidebarGroup({ title, subtitle, children, className }) {
  return (
    <div className={["rounded-lg border border-white/10 bg-slate-900/50 p-2", className].filter(Boolean).join(" ")}>
      <div className="mb-2 flex items-center justify-between gap-3 px-0.5">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{title}</div>
          <div className="text-xs text-slate-500">{subtitle}</div>
        </div>
      </div>
      <div className="grid gap-2">{children}</div>
    </div>
  );
}

function riskApprovalState(selectedRisk, selectedDetail) {
  if (selectedRisk?.is_usable === true || selectedRisk?.decision === "APPROVE") {
    return { label: "Approved", note: selectedRisk?.status || "Risk engine approved", tone: "emerald" };
  }
  if (selectedRisk?.is_usable === false || selectedRisk?.decision === "REJECT") {
    return { label: "Blocked", note: selectedRisk?.status || "Risk engine blocked", tone: "rose" };
  }
  if (selectedDetail.invalidationReason) {
    return { label: "Invalidated", note: selectedDetail.invalidationReason, tone: "rose" };
  }
  return { label: "Pending", note: selectedRisk?.status || "No risk decision", tone: "amber" };
}

function riskMessages(selectedRisk, selectedDetail) {
  const validationErrors = selectedRisk?.validation_errors || [];
  const ignoredReasons = selectedRisk?.ignored_reasons || [];
  const messages = [
    { label: "Decision", value: selectedRisk?.decision || selectedRisk?.status || "Unavailable" },
    { label: "Signal", value: selectedDetail.signalType || "WAIT" },
  ];

  if (validationErrors.length) {
    messages.push({ label: "Errors", value: validationErrors.slice(0, 2).join(" / ") });
  } else if (ignoredReasons.length) {
    messages.push({ label: "Blocks", value: ignoredReasons.slice(0, 2).join(" / ") });
  } else {
    messages.push({ label: "Review", value: selectedRisk?.is_valid_trade_plan === false ? "Trade plan invalid" : "No blocking reason" });
  }

  return messages;
}

function fundingOiSnapshot(selectedDetail) {
  const source = selectedDetail.selectedOrderflow || {};
  const derivatives = selectedDetail.derivatives || {};
  const latestFunding = derivatives?.funding?.latest || null;
  const latestOpenInterest = derivatives?.openInterest?.latest || null;
  const fundingRate =
    latestFunding?.rate ??
    source.funding_rate ??
    source.fundingRate ??
    source.FundingRate;
  const openInterest =
    latestOpenInterest?.value ??
    source.open_interest ??
    source.openInterest ??
    source.OpenInterest;
  const openInterestChangePct = derivatives?.latest_open_interest_change_pct;
  const longPct = normalizeProbability(selectedDetail.longSidePct);
  const shortPct = normalizeProbability(selectedDetail.shortSidePct);

  const fundingHistory = (derivatives?.funding?.history || []).map((item) => ({
    label: formatChartLabel(item.funding_time || item.created_at),
    value: Number(item.rate ?? 0) * 100,
  }));
  const openInterestHistory = (derivatives?.openInterest?.history || []).map((item) => ({
    label: formatChartLabel(item.timestamp || item.created_at),
    value: Number(item.value ?? 0),
  }));

  if (fundingRate !== undefined || openInterest !== undefined) {
    const bias = fundingRate > 0 ? "LONG" : fundingRate < 0 ? "SHORT" : longPct >= shortPct ? "LONG" : "SHORT";
    return {
      bias,
      funding: formatFunding(fundingRate),
      openInterest: formatOpenInterest(openInterest),
      note:
        openInterestChangePct === null || openInterestChangePct === undefined
          ? "Derivative feed available"
          : `Open interest change ${formatPercent(openInterestChangePct, 2, "-")}`,
      tone: bias === "LONG" ? "emerald" : bias === "SHORT" ? "rose" : "slate",
      fundingHistory,
      openInterestHistory,
    };
  }

  if (longPct > shortPct + 15) {
    return { bias: "LONG", funding: "Unavailable", openInterest: "Unavailable", note: "Probability favors long exposure", tone: "emerald", fundingHistory, openInterestHistory };
  }
  if (shortPct > longPct + 15) {
    return { bias: "SHORT", funding: "Unavailable", openInterest: "Unavailable", note: "Probability favors short exposure", tone: "rose", fundingHistory, openInterestHistory };
  }

  return {
    bias: "NEUTRAL",
    funding: "Unavailable",
    openInterest: "Unavailable",
    note: "No derivative feed in current payload",
    tone: "slate",
    fundingHistory,
    openInterestHistory,
  };
}

function compactDerivativeTick(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  const absolute = Math.abs(number);
  if (absolute >= 1_000_000_000) return `${(number / 1_000_000_000).toFixed(1)}B`;
  if (absolute >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (absolute >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return absolute >= 1 ? number.toFixed(2) : number.toFixed(4);
}

function formatChartLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function normalizeProbability(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return number <= 1 ? number * 100 : number;
}

function formatFunding(value) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${formatSigned(number * 100, 4)}%`;
}

function formatOpenInterest(value) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  return formatNumber(value, 0, String(value));
}

function resolveChartPrice(currentPrice, symbol) {
  const direct = Number(currentPrice);
  if (Number.isFinite(direct) && direct > 0) return direct;

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
