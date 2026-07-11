import LiveMarketSection from "../components/LiveMarketSection";

export default function MarketScanPage({
  view,
  auto,
  filters,
  setFilters,
  marketSummary,
  selectedDetail,
  activeTradePlan,
  autoDecision,
  liveStatus,
  watchlist,
  selectedRisk,
  openTrades,
  signalRows,
  paperTradeCandidates,
  onOpenSymbol,
  getSymbolHref,
}) {
  return (
    <LiveMarketSection
      view={view}
      auto={auto}
      filters={filters}
      setFilters={setFilters}
      marketSummary={marketSummary}
      selectedDetail={selectedDetail}
      activeTradePlan={activeTradePlan}
      autoDecision={autoDecision}
      liveStatus={liveStatus}
      watchlist={watchlist}
      selectedRisk={selectedRisk}
      openTrades={openTrades}
      signalRows={signalRows}
      paperTradeCandidates={paperTradeCandidates}
      onOpenSymbol={onOpenSymbol}
      getSymbolHref={getSymbolHref}
    />
  );
}
