import AutomationSection from "../components/AutomationSection";
import DashboardFooter from "../components/DashboardFooter";
import PnLSection from "../components/PnLSection";

export default function TradingDetailsPage({
  view,
  symbols,
  auto,
  setAuto,
  onEmergencyStop,
  autoDecision,
  selectedDetail,
  openTrades,
  selectedPipeline,
  loading,
  realizedPnl,
  unrealizedPnl,
  dailyPnl,
  weeklyPnl,
  monthlyPnl,
  maxDrawdown,
  winningTrades,
  losingTrades,
  winRate,
  tradeHistory,
  openPositions,
  pnlBySymbol,
  pnlBySide,
  equitySeries,
}) {
  return (
    <>
      <AutomationSection
        view={view}
        symbols={symbols}
        auto={auto}
        setAuto={setAuto}
        onEmergencyStop={onEmergencyStop}
        autoDecision={autoDecision}
        selectedDetail={selectedDetail}
        openTrades={openTrades}
      />

      <PnLSection
        realizedPnl={realizedPnl}
        unrealizedPnl={unrealizedPnl}
        dailyPnl={dailyPnl}
        weeklyPnl={weeklyPnl}
        monthlyPnl={monthlyPnl}
        maxDrawdown={maxDrawdown}
        winningTrades={winningTrades}
        losingTrades={losingTrades}
        winRate={winRate}
        tradeHistory={tradeHistory}
        openPositions={openPositions}
        pnlBySymbol={pnlBySymbol}
        pnlBySide={pnlBySide}
        equitySeries={equitySeries}
      />

      <DashboardFooter selectedPipeline={selectedPipeline} loading={loading} />
    </>
  );
}
