import { formatNumber, safeNumber } from "../../utils/formatters";
import { progressToneClass } from "../../utils/toneClasses";

export default function ProgressLine({ label, value, max, tone = "slate" }) {
  const width = max > 0 ? Math.min(100, (safeNumber(value) / max) * 100) : 0;

  return (
    <div className="mb-2">
      <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
        <span>{label}</span>
        <span>{formatNumber(value, 0)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/5">
        <div className={`h-1.5 rounded-full ${progressToneClass(tone)}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}
