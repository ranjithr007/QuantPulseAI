import SignalScannerSection from "../components/SignalScannerSection";

export default function SignalsPage({ view, filters, setView, setFilters, signalRows, watchlist, liveStatus, auto, paperTradeCandidates, onOpenSignal, getSymbolHref }) {
  return (
    <SignalScannerSection
      view={view}
      filters={filters}
      setView={setView}
      setFilters={setFilters}
      signalRows={signalRows}
      watchlist={watchlist}
      liveStatus={liveStatus}
      auto={auto}
      paperTradeCandidates={paperTradeCandidates}
      onOpenSignal={onOpenSignal}
      getSymbolHref={getSymbolHref}
    />
  );
}
