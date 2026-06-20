import clsx from "clsx";
import { accentClass } from "../../utils/toneClasses";

export default function MetricCard({ label, value, note, icon: Icon, accent = "cyan", compact = false }) {
  return (
    <div className={clsx("rounded-lg border border-white/10 bg-slate-950/70 p-4 shadow-lg shadow-slate-950/10", compact && "p-3")}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
          <div className={clsx("mt-2 font-semibold tracking-tight text-white", compact ? "text-xl" : "text-2xl")}>{value}</div>
          {note ? <div className="mt-1 text-xs leading-5 text-slate-400">{note}</div> : null}
        </div>
        {Icon ? (
          <div className={clsx("grid h-10 w-10 shrink-0 place-items-center rounded-lg border", accentClass(accent))}>
            <Icon className="h-4 w-4" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
