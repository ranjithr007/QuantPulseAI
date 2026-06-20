import SignalDetailsSection from "../components/SignalDetailsSection";

export default function CoinDetailsPage({
  view,
  selectedDetail,
  activeTradePlan,
  candleSeries,
  volumeSeries,
  selectedRisk,
  liveStatus,
}) {
  return (
    <SignalDetailsSection
      view={view}
      selectedDetail={selectedDetail}
      activeTradePlan={activeTradePlan}
      candleSeries={candleSeries}
      volumeSeries={volumeSeries}
      selectedRisk={selectedRisk}
      liveStatus={liveStatus}
    />
  );
}
