import ConfidenceRow from "./ConfidenceRow";

export default function SignalQualityPanel({ breakdown = [] }) {
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
