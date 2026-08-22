import clsx from "clsx";
import { accentClass } from "../../utils/toneClasses";

export default function MetricCard({ label, value, note, icon: Icon, accent = "cyan", compact = false, className }) {
  return (
    <div className={clsx("qp-metric-card min-w-0 rounded-xl border border-white/10 bg-slate-950/70 p-3 sm:p-4", compact && "p-3", className)}>
      <div className="flex items-start justify-between gap-2 sm:gap-3">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
          <div className={clsx("mt-2 break-words font-semibold tracking-tight text-white", compact ? "text-xl" : "text-lg sm:text-2xl")}>{value}</div>
          {note ? (
            <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400" title={note}>
              {note}
            </div>
          ) : null}
        </div>
        {Icon ? (
          <div className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-lg border sm:h-10 sm:w-10", accentClass(accent))}>
            <Icon className="h-4 w-4" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
