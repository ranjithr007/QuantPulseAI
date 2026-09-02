import { useMemo } from "react";
import clsx from "clsx";
import {
  Activity,
  BarChart3,
  Brain,
  Clock3,
  Database,
  History,
  Layers3,
  LineChart,
  Lock,
  LogOut,
  Orbit,
  RadioTower,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { formatPercent, formatPrice, formatTimeInIst } from "../utils/formatters";
import { getUnifiedMarketState } from "../utils/liveMarket";
import { selectWatchlistSignal } from "./MarketSignalTable";
import NotificationCenter from "./NotificationCenter";

const PAGE_ITEMS = [
  { id: "dashboard", label: "Dashboard", shortLabel: "Home", icon: BarChart3 },
  { id: "market-scan", label: "Market Scan", shortLabel: "Market", icon: Activity },
  { id: "signals", label: "Signals", shortLabel: "Signals", icon: TrendingUp },
  { id: "market-trend", label: "Market Trend", shortLabel: "Trend", icon: RadioTower },
  { id: "market-move", label: "Market Move", shortLabel: "Move", icon: Zap },
  { id: "strategies", label: "Strategies", shortLabel: "Strategy", icon: Brain },
  { id: "coin-details", label: "Futures Details", shortLabel: "Futures", icon: Activity },
  { id: "risk-controls", label: "Risk Controls", shortLabel: "Risk", icon: ShieldCheck },
  { id: "auto-trading", label: "Auto Trading", shortLabel: "Auto", icon: Lock },
  { id: "pnl", label: "PNL", shortLabel: "PNL", icon: LineChart },
  { id: "backtest", label: "Backtest", shortLabel: "Test", icon: History },
  { id: "rotation", label: "Rotation", shortLabel: "Rot", icon: Orbit },
  { id: "rs-ranking", label: "RS Ranking", shortLabel: "RS", icon: TrendingUp },
  { id: "stage-analysis", label: "Stage Analysis", shortLabel: "Stage", icon: Layers3 },
];

export default function DashboardHeader({
  activePage,
  getPageHref,
  view,
  lastRefresh,
  loading,
  liveStatus,
  selectedDetail,
  symbols,
  modes,
  timeframes,
  signalRows,
  watchlist,
  setView,
  setTick,
  username,
  onLogout,
}) {
  return (
    <>
      <aside className="qp-sidebar fixed inset-y-0 left-0 z-40 hidden w-72 flex-col border-r lg:flex">
        <div className="border-b border-[rgba(255,255,255,0.1)] px-4 py-4">
          <Link to={getPageHref("dashboard")} className="flex min-w-0 items-center gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-cyan-400/25 bg-cyan-500/10 text-cyan-300">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-[#f8fafc]">QuantPulseAI</div>
              <div className="truncate text-xs text-[#94a3b8]">Trading intelligence</div>
            </div>
          </Link>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {PAGE_ITEMS.map((item) => (
            <ShellLink key={item.id} item={item} href={getPageHref(item.id)} active={activePage === item.id} />
          ))}
        </nav>

        <div className="border-t border-[rgba(255,255,255,0.1)] p-4">
          <div className="rounded-xl border border-[rgba(255,255,255,0.1)] bg-[rgba(255,255,255,0.05)] p-3">
            <div className="text-[11px] uppercase tracking-[0.2em] text-[#94a3b8]">Workspace</div>
            <div className="mt-1.5 text-sm font-medium text-[#f8fafc]">{view.symbol}</div>
            <div className="mt-1 text-xs text-[#b7c3d4]">
              {view.timeframe} / {view.mode}
            </div>
          </div>
        </div>
      </aside>

      <header className="qp-topbar sticky top-0 z-30 border-b backdrop-blur-xl lg:ml-72">
        <div className="px-3 py-2 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0 shrink">
                <h1 className="sr-only">Trading intelligence platform</h1>
                <div className="flex flex-wrap items-center gap-1.5 text-xs uppercase tracking-[0.18em] text-slate-500">
                  <span className="font-medium text-slate-300">{activePageLabel(activePage)}</span>
                  <span className="text-slate-700">/</span>
                  <span>{view.symbol}</span>
                <span className="text-slate-700">/</span>
                <span>{view.timeframe}</span>
                <span className="text-slate-700">/</span>
                <span>{view.mode}</span>
              </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                  <Clock3 className="h-3.5 w-3.5" />
                  <span>{lastRefresh ? `Updated ${formatTimeInIst(lastRefresh)}` : "Syncing market data"}</span>
              </div>
            </div>

            <div className="flex min-w-0 items-center justify-end gap-2">
              <SourceStrip selectedDetail={selectedDetail} loading={loading} liveStatus={liveStatus} />
              <NotificationCenter getPageHref={getPageHref} view={view} />
              <button type="button" onClick={onLogout} title={`Sign out ${username}`} aria-label="Sign out" className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-slate-900/80 text-slate-400 transition hover:border-rose-400/30 hover:text-rose-200">
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="mt-2 grid grid-cols-2 gap-2 sm:flex sm:items-start sm:justify-between">
            <div className="contents sm:flex sm:min-w-0 sm:flex-1 sm:flex-wrap sm:items-center sm:gap-1.5">
              <SelectField
                label="Symbol"
                value={view.symbol}
                options={symbols}
                onChange={(symbol) => setView((current) => ({ ...current, symbol }))}
              />
              <SelectField
                label="Mode"
                value={view.mode}
                options={modes}
                onChange={(mode) => setView((current) => ({ ...current, mode }))}
              />
              <div className="col-span-2 min-w-0 sm:flex-none">
                <span className="sr-only">Timeframe</span>
                <div className="flex gap-1 overflow-x-auto pb-1 scrollbar-none sm:flex-wrap sm:overflow-visible sm:pb-0">
                  {timeframes.map((timeframe) => (
                    <button
                      key={timeframe}
                      type="button"
                      onClick={() => setView((current) => ({ ...current, timeframe }))}
                      className={clsx(
                        "h-8 shrink-0 rounded-lg border px-2.5 text-sm transition",
                        view.timeframe === timeframe
                          ? "border-cyan-400/50 bg-cyan-500/15 text-cyan-200"
                          : "border-white/10 bg-slate-900/70 text-slate-300 hover:border-white/20 hover:bg-slate-900"
                      )}
                    >
                      {timeframe}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setTick((value) => value + 1)}
              className="col-span-2 inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-slate-900/80 px-3 text-sm font-medium text-slate-100 transition hover:border-cyan-400/40 hover:bg-slate-800 sm:w-auto"
            >
              <RefreshCw className={clsx("h-4 w-4", loading && "animate-spin")} />
              Refresh
            </button>
          </div>

          <MarketTicker signalRows={signalRows} watchlist={watchlist} view={view} getPageHref={getPageHref} />
        </div>
      </header>

      <MobileNav activePage={activePage} getPageHref={getPageHref} />
    </>
  );
}

function activePageLabel(activePage) {
  return PAGE_ITEMS.find((item) => item.id === activePage)?.label || "Market Scan";
}

function signalPriority(type) {
  if (type === "BUY") return 0;
  if (type === "SELL") return 1;
  return 2;
}

function ShellLink({ item, href, active }) {
  const Icon = item.icon;

  return (
    <NavLink
      to={href}
      className={clsx(
        "flex min-w-0 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition",
        active ? "bg-cyan-400/15 text-[#dff9ff] shadow-sm" : "text-[#b7c3d4] hover:bg-white/5 hover:text-[#f8fafc]"
      )}
    >
      <Icon className={clsx("h-4 w-4", active ? "text-[#6dd7e8]" : "text-[#8292a8]")} />
      <span className="truncate">{item.label}</span>
    </NavLink>
  );
}

function SourceStrip({ selectedDetail, loading, liveStatus }) {
  const marketState = getUnifiedMarketState({
    liveStatus,
    liveRecord: selectedDetail?.liveMarket,
    freshness: selectedDetail?.freshness,
  });
  const liveState = marketState.liveState;
  const candleState = marketState.candleState;
  const liveValue = loading && liveState.state === "FALLBACK"
    ? "Syncing"
    : `${liveState.label}${liveStatus?.cached_count ? ` (${liveStatus.cached_count})` : ""}`;
  const signalText = selectedDetail?.signalType
    ? `${selectedDetail.signalType} ${formatPercent(selectedDetail.confidence, 0, "-")}`
    : "Calculating";

  return (
    <div className="grid min-w-0 flex-1 grid-cols-3 gap-1.5 lg:flex lg:flex-wrap lg:justify-end">
      <SourceChip
        icon={RadioTower}
        label="B WebSocket"
        value={liveValue}
        tone={liveState.tone}
      />
      <SourceChip
        icon={Database}
        label="DB Candle"
        value={candleState.label}
        tone={candleState.tone}
      />
      <SourceChip icon={Brain} label="AI Calculated" value={signalText} tone={selectedDetail?.invalidationReason ? "rose" : "emerald"} />
    </div>
  );
}

function SourceChip({ icon: Icon, label, value, tone }) {
  const toneClass =
    {
      emerald: { text: "text-emerald-300", dot: "bg-emerald-400" },
      cyan: { text: "text-cyan-300", dot: "bg-cyan-400" },
      amber: { text: "text-amber-300", dot: "bg-amber-400" },
      rose: { text: "text-rose-300", dot: "bg-rose-400" },
      slate: { text: "text-slate-300", dot: "bg-slate-400" },
    }[tone || "cyan"] || {
      text: "text-cyan-300",
      dot: "bg-cyan-400",
    };

  return (
    <div className="flex h-8 min-w-0 items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-slate-900/75 px-1.5 sm:justify-start sm:gap-2 sm:px-2.5">
      <div className="hidden items-center gap-1.5 text-[9px] uppercase tracking-[0.12em] text-slate-500 sm:flex">
        <Icon className="h-3.5 w-3.5" />
        <span className="truncate">{label}</span>
      </div>
      <div className="flex min-w-0 items-center gap-1.5">
        <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", toneClass.dot)} />
        <span className={clsx("truncate text-[10px] font-semibold sm:text-xs", toneClass.text)}>{value}</span>
      </div>
    </div>
  );
}

function MarketTicker({ signalRows = [], watchlist, view, getPageHref }) {
  const rows = useMemo(() => {
    const watchRowsBySymbol = new Map(
      (watchlist?.records || []).map((row) => [String(row?.symbol || "").toUpperCase(), row])
    );

    return signalRows
      .map((row) =>
        selectWatchlistSignal(
          row,
          watchRowsBySymbol.get(String(row?.symbol || "").toUpperCase()) || {}
        )
      )
      .sort((a, b) => {
        const priority = signalPriority(a.type) - signalPriority(b.type);
        if (priority !== 0) return priority;
        const confidenceDelta = Number(b.confidence || 0) - Number(a.confidence || 0);
        if (confidenceDelta !== 0) return confidenceDelta;
        return String(a.symbol).localeCompare(String(b.symbol));
      })
      .slice(0, 10);
  }, [signalRows, watchlist]);

  return (
    <div className="market-tape mt-1.5 rounded-lg border border-white/10 bg-slate-900/70 p-1.5">
      <div className="flex items-stretch gap-1.5">
        <div className="flex min-w-[82px] shrink-0 items-center justify-center rounded-md bg-cyan-500/15 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-200 sm:min-w-[94px]">
          <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-cyan-300 shadow-[0_0_0_3px_rgba(34,211,238,0.12)]" />
          Live Scan
        </div>
        <div className="market-tape-viewport min-w-0 flex-1 overflow-x-auto scrollbar-none">
          <div className="flex w-max items-center gap-1.5 pr-1.5">
            {rows.map((row) => (
              <Link
                key={row.symbol}
                to={getPageHref("coin-details", { ...view, symbol: row.symbol })}
                title={row.reason || `${row.symbol} ${row.type}`}
                className="flex h-14 min-w-[132px] shrink-0 flex-col justify-center rounded-lg border border-white/5 bg-slate-950/70 px-2 text-left transition hover:border-cyan-400/30 hover:bg-cyan-500/10 sm:min-w-[150px]"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-white">{row.symbol}</span>
                  <span
                    className={clsx(
                      "text-[10px] font-semibold uppercase tracking-[0.14em]",
                      row.type === "BUY" ? "text-emerald-300" : row.type === "SELL" ? "text-rose-300" : "text-slate-400"
                    )}
                  >
                    {row.type}
                  </span>
                </div>
                <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px]">
                  <span className="text-slate-400">{formatPrice(row.currentPrice, { fallback: "-", compactSmall: true })}</span>
                  <span className="text-cyan-200">
                    {formatPercent(row.confidence, 1, "-")}{row.type === "WAIT" ? " raw" : ""}
                  </span>
                </div>
                <div className="mt-0.5 max-w-[132px] truncate text-[9px] text-slate-500 sm:max-w-[150px]">
                  {row.type === "WAIT" ? row.reason || "No executable confirmation" : "Executable signal"}
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function MobileNav({ activePage, getPageHref }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-white/10 bg-slate-950/95 px-3 py-2 backdrop-blur-xl lg:hidden">
      <div className="flex gap-1 overflow-x-auto scrollbar-none">
        {PAGE_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = activePage === item.id;

          return (
            <NavLink
              key={item.id}
              to={getPageHref(item.id)}
              className={clsx(
                "flex min-w-14 shrink-0 flex-col items-center justify-center gap-1 rounded-lg px-1 py-1.5 text-[11px] font-medium transition",
                active ? "bg-cyan-500/15 text-cyan-100" : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              )}
            >
              <Icon className={clsx("h-4 w-4", active ? "text-cyan-200" : "text-slate-500")} />
              <span className="truncate">{item.shortLabel}</span>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}

function SelectField({ label, value, options, onChange }) {
  return (
    <label className="block w-full sm:w-auto">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 text-sm font-medium text-white outline-none transition hover:border-white/20 focus:border-cyan-400/40 sm:min-w-[120px] sm:w-auto"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}
