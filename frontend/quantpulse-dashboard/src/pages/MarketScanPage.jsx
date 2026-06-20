import LiveMarketSection from "../components/LiveMarketSection";

export default function MarketScanPage({
  view,
  marketSummary,
  selectedDetail,
  activeTradePlan,
  autoDecision,
  liveStatus,
  watchlist,
  openTrades,
  signalRows,
  onOpenSymbol,
  getSymbolHref,
}) {
  return (
    <LiveMarketSection
      view={view}
      marketSummary={marketSummary}
      selectedDetail={selectedDetail}
      activeTradePlan={activeTradePlan}
      autoDecision={autoDecision}
      liveStatus={liveStatus}
      watchlist={watchlist}
      openTrades={openTrades}
      signalRows={signalRows}
      onOpenSymbol={onOpenSymbol}
      getSymbolHref={getSymbolHref}
    />
  );
}
