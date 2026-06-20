export default function InfoLine({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-white/5 bg-slate-950/70 px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="max-w-[70%] text-right text-xs leading-5 text-slate-200">{value}</div>
    </div>
  );
}
