export function pillToneClass(tone) {
  switch (tone) {
    case "emerald":
      return "border-emerald-400/25 bg-emerald-500/10 text-emerald-200";
    case "rose":
      return "border-rose-400/25 bg-rose-500/10 text-rose-200";
    case "amber":
      return "border-amber-400/25 bg-amber-500/10 text-amber-200";
    case "cyan":
      return "border-cyan-400/25 bg-cyan-500/10 text-cyan-200";
    case "slate":
    default:
      return "border-white/10 bg-slate-950/70 text-slate-200";
  }
}

export function accentClass(accent) {
  switch (accent) {
    case "emerald":
      return "border-emerald-400/20 bg-emerald-500/10 text-emerald-200";
    case "rose":
      return "border-rose-400/20 bg-rose-500/10 text-rose-200";
    case "amber":
      return "border-amber-400/20 bg-amber-500/10 text-amber-200";
    case "violet":
      return "border-violet-400/20 bg-violet-500/10 text-violet-200";
    case "cyan":
    default:
      return "border-cyan-400/20 bg-cyan-500/10 text-cyan-200";
  }
}

export function toneBorderClass(tone) {
  switch (tone) {
    case "emerald":
      return "border-emerald-400/20";
    case "rose":
      return "border-rose-400/20";
    case "amber":
      return "border-amber-400/20";
    case "cyan":
      return "border-cyan-400/20";
    default:
      return "border-white/10";
  }
}

export function toneBgClass(tone) {
  switch (tone) {
    case "emerald":
      return "bg-emerald-500/5";
    case "rose":
      return "bg-rose-500/5";
    case "amber":
      return "bg-amber-500/5";
    case "cyan":
      return "bg-cyan-500/5";
    default:
      return "bg-slate-950/70";
  }
}

export function progressToneClass(tone) {
  switch (tone) {
    case "emerald":
      return "bg-emerald-400";
    case "rose":
      return "bg-rose-400";
    case "amber":
      return "bg-amber-400";
    case "cyan":
      return "bg-cyan-400";
    default:
      return "bg-slate-400";
  }
}
