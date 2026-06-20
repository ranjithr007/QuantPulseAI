export default function KeyValueCard({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 p-3">
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-white">{value}</div>
    </div>
  );
}
