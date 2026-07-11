import ConfidenceRow from "./ConfidenceRow";

export default function SignalQualityPanel({ breakdown = [] }) {
  if (!Array.isArray(breakdown) || breakdown.length === 0) {
    return (
      <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-medium text-white">Signal quality</h3>
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Breakdown</span>
        </div>
        <div className="rounded-lg border border-white/10 bg-slate-950/65 px-3 py-4 text-xs text-slate-400">
          No signal breakdown available for the selected timeframe
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-2">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Signal quality</h3>
        <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Breakdown</span>
      </div>
      <div className="space-y-2">
        {breakdown.map((item) => (
          <ConfidenceRow key={item.label} item={item} />
        ))}
      </div>
    </div>
  );
}
