export function savedBacktestSide(records, symbol, timeframe) {
  return [...(records || [])]
    .filter(({ scope }) => scope?.symbol === symbol && scope?.timeframe === timeframe && ["LONG", "SHORT"].includes(scope?.signal))
    .sort((a, b) => String(b.saved_at || "").localeCompare(String(a.saved_at || "")))[0]?.scope.signal || null;
}
