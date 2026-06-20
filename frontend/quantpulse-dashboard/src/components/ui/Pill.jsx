import clsx from "clsx";
import { pillToneClass } from "../../utils/toneClasses";

export default function Pill({ children, tone = "slate" }) {
  return (
    <span className={clsx("inline-flex items-center rounded-full px-3 py-1 text-xs font-medium", pillToneClass(tone))}>
      {children}
    </span>
  );
}
