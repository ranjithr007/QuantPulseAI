import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { tooltipStyle } from "../../utils/formatters";

export default function VolumePanel({ volumeSeries = [] }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Volume</h3>
        <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Bars</span>
      </div>
      <div className="h-36">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={volumeSeries}>
            <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
            <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
            <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
            <Tooltip contentStyle={tooltipStyle()} />
            <Bar dataKey="volume" fill="#38bdf8" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
