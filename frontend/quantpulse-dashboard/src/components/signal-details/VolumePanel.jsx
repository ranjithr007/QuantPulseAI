import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { tooltipStyle } from "../../utils/formatters";

export default function VolumePanel({ volumeSeries = [] }) {
  const hasMeaningfulVolume = Array.isArray(volumeSeries) && volumeSeries.some((point) => Number(point?.volume) > 0);

  if (!Array.isArray(volumeSeries) || volumeSeries.length < 2 || !hasMeaningfulVolume) {
    return (
      <div className="min-w-0 rounded-lg border border-white/10 bg-slate-900/70 p-2">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-medium text-white">Volume</h3>
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Bars</span>
        </div>
        <div className="rounded-lg border border-white/10 bg-slate-950/65 px-3 py-4 text-xs text-slate-400">
          Volume data is not available or does not contain enough history for this timeframe
        </div>
      </div>
    );
  }

  return (
    <div className="min-w-0 rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Volume</h3>
        <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Bars</span>
      </div>
      <div className="h-36 min-w-0 w-full">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 640, height: 144 }}>
          <BarChart data={volumeSeries} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
            <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
            <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} width={42} />
            <Tooltip contentStyle={tooltipStyle()} />
            <Bar dataKey="volume" fill="#38bdf8" radius={[6, 6, 0, 0]} minPointSize={3} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
