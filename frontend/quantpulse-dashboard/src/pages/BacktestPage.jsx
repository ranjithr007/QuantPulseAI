import { useEffect, useMemo, useState } from "react";
import { Activity, BarChart3, LineChart as LineChartIcon, ShieldAlert, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { loadBacktestSummary } from "../hooks/dashboardApi";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { formatDate, formatPercent, formatSigned, safeNumber, tooltipStyle } from "../utils/formatters";

const COLORS = ["#22d3ee", "#34d399", "#f59e0b", "#fb7185", "#a78bfa", "#60a5fa"];

export default function BacktestPage({
  view,
  selectedDetail,
  tradeHistory,
  equitySeries,
  pnlBySymbol,
  dailyPnl,
  weeklyPnl,
  monthlyPnl,
  maxDrawdown,
  winningTrades,
  losingTrades,
  winRate,
}) {
  const [engineSummary, setEngineSummary] = useState(null);
  const [engineError, setEngineError] = useState("");
  const [engineLoading, setEngineLoading] = useState(false);
  const dailySeries = buildDailyPnlSeries(tradeHistory);
  const displayedEquitySeries = useMemo(() => {
    const engineSeries = engineSummary?.result?.equity_curve;
    if (!engineSeries?.length) return equitySeries;
    return engineSeries.map((point) => ({
      label: formatDate(point.label, point.label),
      equity: safeNumber(point.equity, 0),
    }));
  }, [engineSummary, equitySeries]);
  const drawdownSeries = buildDrawdownSeries(displayedEquitySeries);
  const winLossSeries = [
    { name: "Wins", value: winningTrades },
    { name: "Losses", value: losingTrades },
  ];
  const totalClosed = tradeHistory.length;
  const expectancy = calculateExpectancy(tradeHistory);
  const signalSide = signalSideForBacktest(selectedDetail?.signalType);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      if (!view?.symbol || !signalSide) {
        setEngineSummary(null);
        setEngineError("");
        setEngineLoading(false);
        return;
      }

      setEngineLoading(true);
      setEngineError("");

      try {
        const response = await loadBacktestSummary({
          symbol: view.symbol,
          signalSide,
          timeframe: view.timeframe || "15m",
          signal: controller.signal,
        });

        if (!cancelled) {
          setEngineSummary(response);
        }
      } catch (error) {
        if (!cancelled) {
          setEngineSummary(null);
          setEngineError(error instanceof Error ? error.message : "Unable to load backtest summary");
        }
      } finally {
        if (!cancelled) {
          setEngineLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [view?.symbol, view?.timeframe, signalSide]);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Backtest</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Strategy replay and performance</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill tone="cyan">{totalClosed} closed trades</Pill>
            <Pill tone={winRate >= 50 ? "emerald" : "amber"}>{formatPercent(winRate, 0)} win rate</Pill>
          </div>
        </div>

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-6">
          <MetricCard label="Daily PNL" value={formatSigned(dailyPnl)} note="Closed trades" icon={Activity} accent="cyan" />
          <MetricCard label="Weekly PNL" value={formatSigned(weeklyPnl)} note="Closed trades" icon={LineChartIcon} accent="amber" />
          <MetricCard label="Monthly PNL" value={formatSigned(monthlyPnl)} note="Closed trades" icon={BarChart3} accent="violet" />
          <MetricCard label="Max drawdown" value={formatSigned(maxDrawdown)} note="Equity trough" icon={TrendingDown} accent="rose" />
          <MetricCard label="Win / loss" value={`${winningTrades} / ${losingTrades}`} note="Closed outcomes" icon={ShieldCheck} accent="emerald" />
          <MetricCard label="Expectancy" value={formatSigned(expectancy)} note="Average trade PNL" icon={TrendingUp} accent={expectancy >= 0 ? "emerald" : "rose"} />
        </div>

        <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-medium text-white">Backtester V2 summary</div>
              <div className="text-xs text-slate-500">
                {signalSide
                  ? `${view.symbol} ${signalSide} backtest on ${view.timeframe || "15m"}`
                  : "Choose a BUY or SELL signal on the dashboard to run the engine summary."}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Pill tone={signalSide ? "cyan" : "slate"}>{signalSide || "WAIT"}</Pill>
              <Pill tone={engineLoading ? "amber" : engineSummary?.result?.win_rate >= 50 ? "emerald" : "rose"}>
                {engineLoading ? "Running" : engineSummary?.result?.win_rate != null ? `${formatPercent(engineSummary.result.win_rate, 0)} win rate` : "Idle"}
              </Pill>
            </div>
          </div>

          {engineError ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">{engineError}</div> : null}

          {engineSummary?.result ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5 2xl:grid-cols-9">
              <MiniSummary label="Trades" value={engineSummary.result.total_trades} />
              <MiniSummary label="Wins" value={engineSummary.result.wins} />
              <MiniSummary label="Losses" value={engineSummary.result.losses} />
              <MiniSummary label="Profit" value={formatSigned(engineSummary.result.profit)} />
              <MiniSummary label="Profit factor" value={formatSigned(engineSummary.result.profit_factor, 2)} />
              <MiniSummary label="Return" value={formatPercent(engineSummary.result.total_return_percent, 2)} />
              <MiniSummary label="Max drawdown" value={formatPercent(engineSummary.result.max_drawdown_percent, 2)} />
              <MiniSummary label="Trade Sharpe" value={formatSigned(engineSummary.result.sharpe_ratio, 2)} />
              <MiniSummary label="Fees" value={formatSigned(engineSummary.result.fees_paid, 2)} />
            </div>
          ) : null}
        </div>

        <div className="mt-3.5 grid gap-3.5 xl:grid-cols-[1.3fr_0.7fr]">
          <ChartCard title="Equity curve" subtitle="Cumulative closed trade PNL">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={displayedEquitySeries}>
                <defs>
                  <linearGradient id="backtestEquityFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#22d3ee" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value), "Equity"]} />
                <Area type="monotone" dataKey="equity" stroke="#22d3ee" fill="url(#backtestEquityFill)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Win / loss" subtitle="Closed trade outcomes">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={winLossSeries} dataKey="value" nameKey="name" innerRadius={52} outerRadius={86}>
                  <Cell fill="#34d399" />
                  <Cell fill="#fb7185" />
                </Pie>
                <Tooltip contentStyle={tooltipStyle()} />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <div className="mt-3.5 grid gap-3.5 xl:grid-cols-2">
          <ChartCard title="Daily PNL" subtitle="Closed PNL grouped by close date">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dailySeries}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value), "Daily PNL"]} />
                <Bar dataKey="pnl" radius={[6, 6, 0, 0]}>
                  {dailySeries.map((item) => (
                    <Cell key={item.label} fill={item.pnl >= 0 ? "#34d399" : "#fb7185"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Drawdown" subtitle="Peak-to-trough drift from equity high">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={drawdownSeries}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value), "Drawdown"]} />
                <Line type="monotone" dataKey="drawdown" stroke="#fb7185" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <div className="mt-3.5 grid gap-3.5 xl:grid-cols-[0.9fr_1.1fr]">
          <ChartCard title="PNL by symbol" subtitle="Closed trade contribution">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={pnlBySymbol} layout="vertical">
                <CartesianGrid stroke="rgba(148,163,184,0.12)" horizontal={false} />
                <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "#cbd5e1", fontSize: 11 }} width={80} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value), "PNL"]} />
                <Bar dataKey="value" radius={[0, 8, 8, 0]}>
                  {pnlBySymbol.map((entry, index) => (
                    <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          <BacktestTrades tradeHistory={tradeHistory} />
        </div>

        {engineSummary?.result?.trades?.length ? (
          <div className="mt-3.5 overflow-hidden rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">Engine trades</div>
                <div className="text-xs text-slate-500">Latest simulated trades from the backtest engine</div>
              </div>
              <Pill tone="cyan">{engineSummary.result.trades.length} samples</Pill>
            </div>
            <div className="mt-2.5 overflow-x-auto">
              <table className="min-w-full divide-y divide-white/5 text-sm">
                <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                  <tr>
                    <th className="px-3 py-2.5 text-left">Entry</th>
                    <th className="px-3 py-2.5 text-left">Stop</th>
                    <th className="px-3 py-2.5 text-left">Target</th>
                    <th className="px-3 py-2.5 text-left">PnL</th>
                    <th className="px-3 py-2.5 text-left">Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {engineSummary.result.trades.slice(0, 10).map((trade, index) => (
                    <tr key={`${trade.entry}-${index}`} className="bg-slate-950/35">
                      <td className="px-3 py-2.5 text-slate-300">{formatSigned(trade.entry, 2, "-")}</td>
                      <td className="px-3 py-2.5 text-slate-300">{formatSigned(trade.stop, 2, "-")}</td>
                      <td className="px-3 py-2.5 text-slate-300">{formatSigned(trade.target, 2, "-")}</td>
                      <td className={trade.pnl >= 0 ? "px-3 py-2.5 font-medium text-emerald-300" : "px-3 py-2.5 font-medium text-rose-300"}>
                        {formatSigned(trade.pnl, 2, "-")}
                      </td>
                      <td className="px-3 py-2.5 text-slate-300">{trade.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{title}</div>
          <div className="text-xs text-slate-500">{subtitle}</div>
        </div>
      </div>
      <div className="h-60">{children}</div>
    </div>
  );
}

function BacktestTrades({ tradeHistory }) {
  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Replay samples</div>
          <div className="text-xs text-slate-500">Most recent closed trades</div>
        </div>
        <Pill tone="slate">{tradeHistory.length} closed</Pill>
      </div>
      <div className="mt-2.5 overflow-x-auto">
        <table className="min-w-full divide-y divide-white/5 text-sm">
          <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            <tr>
              <th className="px-3 py-2.5 text-left">Symbol</th>
              <th className="px-3 py-2.5 text-left">Side</th>
              <th className="px-3 py-2.5 text-left">PNL</th>
              <th className="px-3 py-2.5 text-left">Result</th>
              <th className="px-3 py-2.5 text-left">Closed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {tradeHistory.slice(0, 10).map((trade) => (
              <tr key={trade.id} className="bg-slate-950/35">
                <td className="px-3 py-2.5 text-white">{trade.symbol}</td>
                <td className="px-3 py-2.5 text-slate-300">{trade.side}</td>
                <td className={safeNumber(trade.pnl_percent, 0) >= 0 ? "px-3 py-2.5 font-medium text-emerald-300" : "px-3 py-2.5 font-medium text-rose-300"}>
                  {formatSigned(trade.pnl_percent)}
                </td>
                <td className="px-3 py-2.5 text-slate-300">{trade.result || "N/A"}</td>
                <td className="px-3 py-2.5 text-slate-400">{formatDate(trade.closed_at || trade.created_at)}</td>
              </tr>
            ))}
            {!tradeHistory.length ? (
              <tr>
                <td className="px-3 py-3.5 text-slate-400" colSpan={5}>
                  No closed trades available for replay.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function buildDailyPnlSeries(trades) {
  const groups = new Map();

  trades.forEach((trade) => {
    const date = new Date(trade.closed_at || trade.created_at || 0);
    const key = Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 10) : "Unknown";
    groups.set(key, (groups.get(key) || 0) + safeNumber(trade.pnl_percent, 0));
  });

  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, pnl]) => ({ label: label.slice(5), pnl: Number(pnl.toFixed(2)) }));
}

function buildDrawdownSeries(series) {
  let peak = -Infinity;

  return series.map((point) => {
    peak = Math.max(peak, safeNumber(point.equity, 0));
    return {
      label: point.label,
      drawdown: Number((safeNumber(point.equity, 0) - peak).toFixed(2)),
    };
  });
}

function calculateExpectancy(trades) {
  if (!trades.length) return 0;
  return Number((trades.reduce((sum, trade) => sum + safeNumber(trade.pnl_percent, 0), 0) / trades.length).toFixed(2));
}

function signalSideForBacktest(signalType) {
  if (signalType === "BUY") return "LONG";
  if (signalType === "SELL") return "SHORT";
  return null;
}

function MiniSummary({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-white">{value ?? "-"}</div>
    </div>
  );
}
