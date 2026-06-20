import clsx from "clsx";
import {
  Activity,
  BarChart3,
  LineChart as LineChartIcon,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import MetricCard from "./ui/MetricCard";
import Pill from "./ui/Pill";
import { formatDate, formatPercent, formatPrice, formatSigned, safeNumber, tooltipStyle } from "../utils/formatters";

const CHART_COLORS = ["#22d3ee", "#34d399", "#f59e0b", "#fb7185", "#a78bfa", "#60a5fa"];

export default function PnLSection({
  realizedPnl,
  unrealizedPnl,
  dailyPnl,
  weeklyPnl,
  monthlyPnl,
  maxDrawdown,
  winningTrades,
  losingTrades,
  winRate,
  tradeHistory,
  openPositions,
  pnlBySymbol,
  pnlBySide,
  equitySeries,
}) {
  const totalTrades = tradeHistory.length + openPositions.length;
  const avgProfit = averagePnl(tradeHistory, true);
  const avgLoss = averagePnl(tradeHistory, false);

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">PnL Dashboard</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Trade performance</h2>
          </div>
        </div>

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-6">
          <MetricCard label="Total unrealized PnL" value={formatSigned(unrealizedPnl)} note="Open PnL" icon={TrendingUp} accent="emerald" />
          <MetricCard label="Total realized PnL" value={formatSigned(realizedPnl)} note="Closed PnL" icon={TrendingDown} accent="rose" />
          <MetricCard label="Daily PnL" value={formatSigned(dailyPnl)} note="Closed trades" icon={Activity} accent="cyan" />
          <MetricCard label="Weekly PnL" value={formatSigned(weeklyPnl)} note="Closed trades" icon={LineChartIcon} accent="amber" />
          <MetricCard label="Monthly PnL" value={formatSigned(monthlyPnl)} note="Closed trades" icon={BarChart3} accent="violet" />
          <MetricCard label="Win rate" value={formatPercent(winRate)} note={`${winningTrades} wins / ${losingTrades} losses`} icon={ShieldCheck} accent="emerald" />
        </div>

        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Total trades" value={totalTrades} note="Open + closed" icon={Wallet} accent="cyan" compact />
          <MetricCard label="Winning trades" value={winningTrades} note="Closed trades" icon={ShieldCheck} accent="emerald" compact />
          <MetricCard label="Losing trades" value={losingTrades} note="Closed trades" icon={ShieldAlert} accent="rose" compact />
          <MetricCard label="Avg profit / loss" value={`${formatSigned(avgProfit)} / ${formatSigned(avgLoss)}`} note="Closed samples" icon={BarChart3} accent="amber" compact />
        </div>

        <div className="mt-3.5 grid gap-3.5 xl:grid-cols-[1.35fr_0.65fr]">
          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">Equity curve</div>
                <div className="text-xs text-slate-500">Cumulative closed trade PnL</div>
              </div>
              <Pill tone="cyan">{formatSigned(maxDrawdown)} max drawdown</Pill>
            </div>
            <div className="h-60">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equitySeries}>
                  <defs>
                    <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#22d3ee" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <Tooltip contentStyle={tooltipStyle()} />
                  <Area type="monotone" dataKey="equity" stroke="#22d3ee" fill="url(#equityFill)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">PnL mix</div>
                <div className="text-xs text-slate-500">Closed trades by signal type</div>
              </div>
              <Pill tone="slate">{tradeHistory.length} closed</Pill>
            </div>
            <div className="h-36">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pnlBySide} dataKey="value" nameKey="name" innerRadius={35} outerRadius={65}>
                    {pnlBySide.map((entry, index) => (
                      <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => [formatSigned(value), "PnL"]} contentStyle={tooltipStyle()} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-2 space-y-1.5">
              {pnlBySide.map((item, index) => (
                <div key={item.name} className="flex items-center justify-between rounded-lg border border-white/10 bg-slate-950/70 px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }} />
                    <span className="text-sm text-slate-300">{item.name}</span>
                  </div>
                  <span className="text-sm font-medium text-white">{formatSigned(item.value)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-3.5 grid gap-3.5 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">PNL by symbol</div>
                <div className="text-xs text-slate-500">Closed trade performance</div>
              </div>
            </div>
            <div className="h-60">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pnlBySymbol} layout="vertical">
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" horizontal={false} />
                  <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "#cbd5e1", fontSize: 11 }} width={80} />
                  <Tooltip formatter={(value) => [formatSigned(value), "PnL"]} contentStyle={tooltipStyle()} />
                  <Bar dataKey="value" radius={[0, 8, 8, 0]}>
                    {pnlBySymbol.map((entry, index) => (
                      <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <OpenPositionsTable openPositions={openPositions} />
        </div>

        <TradeHistoryTable tradeHistory={tradeHistory} />
      </div>
    </section>
  );
}

function OpenPositionsTable({ openPositions }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Open positions</div>
          <div className="text-xs text-slate-500">Current open paper trades</div>
        </div>
        <Pill tone="cyan">{openPositions.length} open</Pill>
      </div>
      <div className="overflow-hidden rounded-lg border border-white/10">
        <table className="min-w-full divide-y divide-white/5 text-sm">
          <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            <tr>
              <th className="px-3 py-2.5 text-left">Symbol</th>
              <th className="px-3 py-2.5 text-left">Side</th>
              <th className="px-3 py-2.5 text-left">Entry</th>
              <th className="px-3 py-2.5 text-left">Current</th>
              <th className="px-3 py-2.5 text-left">PnL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {openPositions.slice(0, 8).map((trade) => (
              <tr key={trade.id} className="bg-slate-950/40">
                <td className="px-3 py-2.5 text-white">{trade.symbol}</td>
                <td className="px-3 py-2.5">
                  <Pill tone={trade.side === "LONG" ? "emerald" : "rose"}>{trade.side}</Pill>
                </td>
                <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.entry_price)}</td>
                <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.current_price)}</td>
                <td className={clsx("px-3 py-2.5 font-medium", trade.unrealized_pnl_percent >= 0 ? "text-emerald-300" : "text-rose-300")}>
                  {formatSigned(trade.unrealized_pnl_percent)}
                </td>
              </tr>
            ))}
            {!openPositions.length ? (
              <tr>
                <td className="px-3 py-3.5 text-slate-400" colSpan={5}>
                  No open paper positions.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TradeHistoryTable({ tradeHistory }) {
  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Trade history</div>
          <div className="text-xs text-slate-500">Closed paper trades</div>
        </div>
        <Pill tone="slate">{tradeHistory.length} closed</Pill>
      </div>
      <div className="mt-2.5 overflow-x-auto">
        <table className="min-w-full divide-y divide-white/5 text-sm">
          <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            <tr>
              <th className="px-3 py-2.5 text-left">Symbol</th>
              <th className="px-3 py-2.5 text-left">Side</th>
              <th className="px-3 py-2.5 text-left">Entry</th>
              <th className="px-3 py-2.5 text-left">Exit</th>
              <th className="px-3 py-2.5 text-left">PnL</th>
              <th className="px-3 py-2.5 text-left">Result</th>
              <th className="px-3 py-2.5 text-left">Closed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {tradeHistory.slice(0, 12).map((trade) => (
              <tr key={trade.id} className="bg-slate-950/35">
                <td className="px-3 py-2.5 text-white">{trade.symbol}</td>
                <td className="px-3 py-2.5">
                  <Pill tone={trade.side === "LONG" ? "emerald" : "rose"}>{trade.side}</Pill>
                </td>
                <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.entry_price)}</td>
                <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.exit_price)}</td>
                <td className={clsx("px-3 py-2.5 font-medium", safeNumber(trade.pnl_percent, 0) >= 0 ? "text-emerald-300" : "text-rose-300")}>
                  {formatSigned(trade.pnl_percent)}
                </td>
                <td className="px-3 py-2.5 text-slate-300">{trade.result || "N/A"}</td>
                <td className="px-3 py-2.5 text-slate-400">{formatDate(trade.closed_at || trade.created_at)}</td>
              </tr>
            ))}
            {!tradeHistory.length ? (
              <tr>
                <td className="px-3 py-3.5 text-slate-400" colSpan={7}>
                  No closed trades available.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function averagePnl(trades, positive) {
  const items = trades.filter((trade) => (safeNumber(trade.pnl_percent, 0) > 0) === positive);
  if (!items.length) return 0;
  return Number((items.reduce((sum, trade) => sum + safeNumber(trade.pnl_percent, 0), 0) / items.length).toFixed(2));
}
