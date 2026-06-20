import Pill from "../ui/Pill";
import { formatSigned } from "../../utils/formatters";
import { progressToneClass } from "../../utils/toneClasses";

export default function ConfidenceRow({ item }) {
  const tone = item.score >= 20 ? "emerald" : item.score <= 0 ? "rose" : "amber";

  return (
    <div className="rounded-lg border border-white/5 bg-slate-950/70 p-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{item.label}</div>
          <div className="mt-0.5 text-xs text-slate-500">{item.reason}</div>
        </div>
        <Pill tone={tone}>{formatSigned(item.score, 0)}</Pill>
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-white/5">
        <div className={`h-1.5 rounded-full ${progressToneClass(tone)}`} style={{ width: `${item.width}%` }} />
      </div>
    </div>
  );
}
