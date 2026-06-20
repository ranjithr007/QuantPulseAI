import SignalScannerSection from "../components/SignalScannerSection";

export default function SignalsPage({ view, filters, setView, setFilters, signalRows, watchlist, liveStatus, onOpenSignal, getSymbolHref }) {
  return (
    <SignalScannerSection
      view={view}
      filters={filters}
      setView={setView}
      setFilters={setFilters}
      signalRows={signalRows}
      watchlist={watchlist}
      liveStatus={liveStatus}
      onOpenSignal={onOpenSignal}
      getSymbolHref={getSymbolHref}
    />
  );
}
