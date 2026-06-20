import clsx from "clsx";
import { toneBgClass, toneBorderClass } from "../../utils/toneClasses";

export default function MiniCounter({ label, value, tone = "slate" }) {
  return (
    <div className={clsx("rounded-lg border p-3", toneBorderClass(tone), toneBgClass(tone))}>
      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
    </div>
  );
}
