import { useEffect, useMemo, useState } from "react";
import { Activity, BarChart3, LineChart as LineChartIcon, ShieldAlert, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  exportPhase2ValidationReport,
  loadBacktestSummary,
  loadPhase2ValidationArtifact,
  loadPhase2ValidationHistory,
  loadPhase2ValidationReport,
  loadPhase2ValidationSummary,
  loadWalkForwardSummary,
} from "../hooks/dashboardApi";
import MetricCard from "../components/ui/MetricCard";
import Pill from "../components/ui/Pill";
import { formatDate, formatPercent, formatSigned, safeNumber, tooltipStyle } from "../utils/formatters";

const COLORS = ["#22d3ee", "#34d399", "#f59e0b", "#fb7185", "#a78bfa", "#60a5fa"];

export default function BacktestPage({
  view,
  selectedDetail,
  tradeHistory,
  equitySeries,
  pnlBySymbol,
  dailyPnl,
  weeklyPnl,
  monthlyPnl,
  maxDrawdown,
  winningTrades,
  losingTrades,
  winRate,
}) {
  const [engineSummary, setEngineSummary] = useState(null);
  const [engineError, setEngineError] = useState("");
  const [engineLoading, setEngineLoading] = useState(false);
  const [walkForwardSummary, setWalkForwardSummary] = useState(null);
  const [walkForwardError, setWalkForwardError] = useState("");
  const [walkForwardLoading, setWalkForwardLoading] = useState(false);
  const [phase2ReportSummary, setPhase2ReportSummary] = useState(null);
  const [phase2ReportError, setPhase2ReportError] = useState("");
  const [phase2ReportLoading, setPhase2ReportLoading] = useState(false);
  const [phase2ExportLoading, setPhase2ExportLoading] = useState(false);
  const [phase2ExportError, setPhase2ExportError] = useState("");
  const [phase2ExportResult, setPhase2ExportResult] = useState(null);
  const [phase2History, setPhase2History] = useState([]);
  const [phase2HistoryError, setPhase2HistoryError] = useState("");
  const [phase2HistoryLoading, setPhase2HistoryLoading] = useState(false);
  const [phase2ScopeSummary, setPhase2ScopeSummary] = useState([]);
  const [phase2ScopeSummaryError, setPhase2ScopeSummaryError] = useState("");
  const [phase2ScopeSummaryLoading, setPhase2ScopeSummaryLoading] = useState(false);
  const [phase2ScopeTimeframeFilter, setPhase2ScopeTimeframeFilter] = useState("ALL");
  const [phase2ScopeStatusFilter, setPhase2ScopeStatusFilter] = useState("ALL");
  const [phase2ScopeSort, setPhase2ScopeSort] = useState("LATEST");
  const [phase2ReviewMode, setPhase2ReviewMode] = useState("ALL");
  const [phase2Enabled, setPhase2Enabled] = useState(false);
  const [selectedArtifact, setSelectedArtifact] = useState(null);
  const [selectedArtifactError, setSelectedArtifactError] = useState("");
  const [selectedArtifactLoading, setSelectedArtifactLoading] = useState(false);
  const engineResult = engineSummary?.result || null;
  const executionParity = engineResult?.execution_parity || null;
  const eligibilityDivergence = engineResult?.eligibility_divergence || null;
  const pointInTimeCoverage = engineResult?.replay_provenance?.point_in_time_coverage || null;
  const replayDecisionSummary = engineResult?.decision_summary || null;
  const walkForwardResult = walkForwardSummary?.result || null;
  const validationContract = walkForwardResult?.validation_contract || null;
  const phase2Report = phase2ReportSummary?.report || null;
  const engineTrades = engineResult?.trades || [];
  const displayTradeHistory = useMemo(() => {
    if (!engineTrades.length) return tradeHistory;
    return [...engineTrades].sort((a, b) => tradeDateValue(b) - tradeDateValue(a));
  }, [engineTrades, tradeHistory]);
  const displayedDailyPnl = engineTrades.length ? sumTradesWithinDays(engineTrades, 1) : dailyPnl;
  const displayedWeeklyPnl = engineTrades.length ? sumTradesWithinDays(engineTrades, 7) : weeklyPnl;
  const displayedMonthlyPnl = engineTrades.length ? sumTradesWithinDays(engineTrades, 30) : monthlyPnl;
  const displayedWinningTrades = engineResult?.wins ?? winningTrades;
  const displayedLosingTrades = engineResult?.losses ?? losingTrades;
  const displayedWinRate = engineResult?.win_rate ?? winRate;
  const displayedMaxDrawdown = engineResult?.max_drawdown ?? maxDrawdown;
  const displayedPnlBySymbol = useMemo(() => {
    if (!engineTrades.length) return pnlBySymbol;
    return [{
      name: view.symbol,
      value: Number(engineTrades.reduce((sum, trade) => sum + tradePnlValue(trade), 0).toFixed(2)),
    }];
  }, [engineTrades, pnlBySymbol, view.symbol]);
  const dailySeries = buildDailyPnlSeries(displayTradeHistory);
  const displayedEquitySeries = useMemo(() => {
    const engineSeries = engineResult?.equity_curve;
    if (!engineSeries?.length) return equitySeries;
    return engineSeries.map((point) => ({
      label: formatDate(point.label, point.label),
      equity: safeNumber(point.equity, 0),
    }));
  }, [engineResult, equitySeries]);
  const phase2ScopeTimeframeOptions = useMemo(() => {
    return Array.from(
      new Set((phase2ScopeSummary || []).map((item) => item?.scope?.timeframe).filter(Boolean))
    ).sort(timeframeSortOrder);
  }, [phase2ScopeSummary]);
  const filteredPhase2ScopeSummary = useMemo(() => {
    const records = [...(phase2ScopeSummary || [])].filter((item) => {
      if (phase2ScopeTimeframeFilter !== "ALL" && item?.scope?.timeframe !== phase2ScopeTimeframeFilter) return false;
      if (phase2ScopeStatusFilter !== "ALL" && item?.overall_status !== phase2ScopeStatusFilter) return false;
      return true;
    });
    records.sort((left, right) => comparePhase2SummaryRecords(left, right, phase2ScopeSort));
    return records;
  }, [phase2ScopeSort, phase2ScopeStatusFilter, phase2ScopeSummary, phase2ScopeTimeframeFilter]);
  const phase2Leaderboard = useMemo(() => buildPhase2Leaderboard(filteredPhase2ScopeSummary), [filteredPhase2ScopeSummary]);
  const phase2SetupFamilySummary = useMemo(
    () => buildPhase2SetupFamilySummary(filteredPhase2ScopeSummary),
    [filteredPhase2ScopeSummary]
  );
  const phase2ReviewSummary = useMemo(
    () => buildPhase2ReviewSummary(filteredPhase2ScopeSummary),
    [filteredPhase2ScopeSummary]
  );
  const displayedPhase2ScopeSummary = useMemo(() => {
    return (filteredPhase2ScopeSummary || []).filter((item) => matchesPhase2ReviewMode(item, phase2ReviewMode));
  }, [filteredPhase2ScopeSummary, phase2ReviewMode]);
  const promotionScorecard = useMemo(
    () => buildPromotionScorecard(phase2Report, walkForwardResult),
    [phase2Report, walkForwardResult]
  );
  const phase3EntryGate = useMemo(
    () => buildPhase3EntryGate(phase2Report, walkForwardResult, promotionScorecard),
    [phase2Report, walkForwardResult, promotionScorecard]
  );
  const drawdownSeries = buildDrawdownSeries(displayedEquitySeries);
  const winLossSeries = [
    { name: "Wins", value: displayedWinningTrades },
    { name: "Losses", value: displayedLosingTrades },
  ];
  const totalClosed = engineResult?.total_trades ?? displayTradeHistory.length;
  const expectancy = calculateExpectancy(displayTradeHistory);
  const { signalSide, signalSideSource } = deriveBacktestSignalSide(selectedDetail?.signalType, view.symbol, tradeHistory);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function loadEngineSummary() {
      if (!view?.symbol || !signalSide) {
        setEngineSummary(null);
        setEngineError("");
        setEngineLoading(false);
        return;
      }

      setEngineLoading(true);
      setEngineError("");

      try {
        const backtestResult = await loadBacktestSummary({
          symbol: view.symbol,
          signalSide,
          timeframe: view.timeframe || "1h",
          signal: controller.signal,
        });

        if (cancelled) {
          return;
        }

        setEngineSummary(backtestResult);
      } catch (error) {
        if (!cancelled) {
          setEngineSummary(null);
          setEngineError(error instanceof Error ? error.message : "Unable to load backtest summary");
        }
      } finally {
        if (!cancelled) {
          setEngineLoading(false);
        }
      }
    }

    loadEngineSummary();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [view?.symbol, view?.timeframe, signalSide]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function loadPhase2() {
      if (!view?.symbol || !signalSide || !phase2Enabled) {
        setWalkForwardSummary(null);
        setWalkForwardError("");
        setWalkForwardLoading(false);
        setPhase2ReportSummary(null);
        setPhase2ReportError("");
        setPhase2ReportLoading(false);
        setPhase2History([]);
        setPhase2HistoryError("");
        setPhase2HistoryLoading(false);
        setPhase2ScopeSummary([]);
        setPhase2ScopeSummaryError("");
        setPhase2ScopeSummaryLoading(false);
        setSelectedArtifact(null);
        setSelectedArtifactError("");
        setSelectedArtifactLoading(false);
        return;
      }

      setWalkForwardLoading(true);
      setWalkForwardError("");
      setPhase2ReportLoading(true);
      setPhase2ReportError("");
      setPhase2HistoryLoading(true);
      setPhase2HistoryError("");
      setPhase2ScopeSummaryLoading(true);
      setPhase2ScopeSummaryError("");
      setSelectedArtifact(null);
      setSelectedArtifactError("");
      setSelectedArtifactLoading(false);

      try {
        const [walkForwardResponse, phase2ReportResponse, phase2HistoryResponse, phase2SummaryResponse] = await Promise.allSettled([
          loadWalkForwardSummary({
            symbol: view.symbol,
            signalSide,
            timeframe: view.timeframe || "1h",
            signal: controller.signal,
          }),
          loadPhase2ValidationReport({
            symbol: view.symbol,
            signalSide,
            timeframe: view.timeframe || "1h",
            signal: controller.signal,
          }),
          loadPhase2ValidationHistory({
            symbol: view.symbol,
            timeframe: view.timeframe || "1h",
            signalSide,
            limit: 8,
            signal: controller.signal,
          }),
          loadPhase2ValidationSummary({
            signalSide,
            limit: 12,
            signal: controller.signal,
          }),
        ]);

        if (cancelled) {
          return;
        }

        if (walkForwardResponse.status === "fulfilled") {
          setWalkForwardSummary(walkForwardResponse.value);
        } else {
          setWalkForwardSummary(null);
          setWalkForwardError(walkForwardResponse.reason instanceof Error ? walkForwardResponse.reason.message : "Unable to load walk-forward summary");
        }

        if (phase2ReportResponse.status === "fulfilled") {
          setPhase2ReportSummary(phase2ReportResponse.value);
        } else {
          setPhase2ReportSummary(null);
          setPhase2ReportError(phase2ReportResponse.reason instanceof Error ? phase2ReportResponse.reason.message : "Unable to load Phase 2 validation report");
        }

        if (phase2HistoryResponse.status === "fulfilled") {
          setPhase2History(phase2HistoryResponse.value?.records || []);
        } else {
          setPhase2History([]);
          setPhase2HistoryError(phase2HistoryResponse.reason instanceof Error ? phase2HistoryResponse.reason.message : "Unable to load Phase 2 validation history");
        }

        if (phase2SummaryResponse.status === "fulfilled") {
          setPhase2ScopeSummary(phase2SummaryResponse.value?.records || []);
        } else {
          setPhase2ScopeSummary([]);
          setPhase2ScopeSummaryError(phase2SummaryResponse.reason instanceof Error ? phase2SummaryResponse.reason.message : "Unable to load cross-scope Phase 2 summary");
        }
      } finally {
        if (!cancelled) {
          setWalkForwardLoading(false);
          setPhase2ReportLoading(false);
          setPhase2HistoryLoading(false);
          setPhase2ScopeSummaryLoading(false);
        }
      }
    }

    loadPhase2();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [view?.symbol, view?.timeframe, signalSide, phase2Enabled]);

  async function handleExportPhase2Report() {
    if (!view?.symbol || !signalSide) {
      setPhase2ExportError("Choose a BUY or SELL signal before exporting the Phase 2 report.");
      setPhase2ExportResult(null);
      return;
    }

    const controller = new AbortController();
    setPhase2ExportLoading(true);
    setPhase2ExportError("");

    try {
      const response = await exportPhase2ValidationReport({
        symbol: view.symbol,
        signalSide,
        timeframe: view.timeframe || "1h",
        signal: controller.signal,
      });
      setPhase2ExportResult(response?.artifact || null);
      setPhase2History((current) => [response?.artifact, ...current].filter(Boolean).slice(0, 8));
    } catch (error) {
      setPhase2ExportResult(null);
      setPhase2ExportError(error instanceof Error ? error.message : "Unable to export Phase 2 validation report");
    } finally {
      setPhase2ExportLoading(false);
      controller.abort();
    }
  }

  async function handleLoadArtifact(artifactId) {
    if (!artifactId) return;
    const controller = new AbortController();
    setSelectedArtifactLoading(true);
    setSelectedArtifactError("");
    try {
      const response = await loadPhase2ValidationArtifact({
        artifactId,
        signal: controller.signal,
      });
      setSelectedArtifact(response || null);
    } catch (error) {
      setSelectedArtifact(null);
      setSelectedArtifactError(error instanceof Error ? error.message : "Unable to load saved Phase 2 artifact");
    } finally {
      setSelectedArtifactLoading(false);
      controller.abort();
    }
  }

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Backtest</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Strategy replay and performance</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill tone="cyan">{totalClosed} closed trades</Pill>
            <Pill tone={displayedWinRate >= 50 ? "emerald" : "amber"}>{formatPercent(displayedWinRate, 0)} win rate</Pill>
          </div>
        </div>

        <div className="mt-3.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-6">
          <MetricCard label="Daily PNL" value={formatSigned(displayedDailyPnl)} note="Closed trades" icon={Activity} accent="cyan" />
          <MetricCard label="Weekly PNL" value={formatSigned(displayedWeeklyPnl)} note="Closed trades" icon={LineChartIcon} accent="amber" />
          <MetricCard label="Monthly PNL" value={formatSigned(displayedMonthlyPnl)} note="Closed trades" icon={BarChart3} accent="violet" />
          <MetricCard label="Max drawdown" value={formatSigned(displayedMaxDrawdown)} note="Equity trough" icon={TrendingDown} accent="rose" />
          <MetricCard label="Win / loss" value={`${displayedWinningTrades} / ${displayedLosingTrades}`} note="Closed outcomes" icon={ShieldCheck} accent="emerald" />
          <MetricCard label="Expectancy" value={formatSigned(expectancy)} note="Average trade PNL" icon={TrendingUp} accent={expectancy >= 0 ? "emerald" : "rose"} />
        </div>

        <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-medium text-white">Filtered strategy replay</div>
              <div className="text-xs text-slate-500">
                {signalSide
                  ? `${view.symbol} ${signalSide} candle-regime filter on ${view.timeframe || "1h"}${signalSideSource === "history" ? " (recent history fallback)" : ""}`
                  : "Choose a BUY or SELL signal on the dashboard to run the engine summary."}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Pill tone={signalSide ? "cyan" : "slate"}>{signalSide || "WAIT"}</Pill>
              <Pill tone={engineLoading ? "amber" : engineSummary?.result?.win_rate >= 50 ? "emerald" : "rose"}>
                {engineLoading ? "Running" : engineSummary?.result?.win_rate != null ? `${formatPercent(engineSummary.result.win_rate, 0)} win rate` : "Idle"}
              </Pill>
            </div>
          </div>

          {engineError ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">{engineError}</div> : null}

          {engineSummary?.result ? (
            <>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5 2xl:grid-cols-9">
              <MiniSummary label="Trades" value={engineSummary.result.total_trades} />
              <MiniSummary label="Wins" value={engineSummary.result.wins} />
              <MiniSummary label="Losses" value={engineSummary.result.losses} />
              <MiniSummary label="Profit" value={formatSigned(engineSummary.result.profit)} />
              <MiniSummary label="Profit factor" value={formatSigned(engineSummary.result.profit_factor, 2)} />
              <MiniSummary label="Return" value={formatPercent(engineSummary.result.total_return_percent, 2)} />
              <MiniSummary label="Max drawdown" value={formatPercent(engineSummary.result.max_drawdown_percent, 2)} />
              <MiniSummary label="Trade Sharpe" value={formatSigned(engineSummary.result.sharpe_ratio, 2)} />
              <MiniSummary label="Fees" value={formatSigned(engineSummary.result.fees_paid, 2)} />
            </div>
            <div className="mt-2 text-xs text-slate-500">
              {engineSummary.result.strategy} · next-candle entry · ATR {engineSummary.result.assumptions?.stop_atr_multiple ?? 1.5} stop / {engineSummary.result.assumptions?.target_atr_multiple ?? 3.5} target · historical SMC and order flow unavailable
            </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-2">
              <DiagnosticStrip
                label="Replay decisions"
                value={replayDecisionSummary?.evaluated}
                note="Closed-candle setups evaluated"
                tone="cyan"
              />
              <DiagnosticStrip
                label="Top replay blocker"
                value={topReplayBlockerLabel(replayDecisionSummary?.rejections)}
                note={topReplayBlockerCountNote(replayDecisionSummary?.rejections)}
                tone="rose"
              />
              <DiagnosticStrip
                label="Point-in-time coverage"
                value={coverageLabel(pointInTimeCoverage)}
                note={coverageDiagnosticNote(pointInTimeCoverage)}
                tone={coverageTone(pointInTimeCoverage)}
              />
              <DiagnosticStrip
                label="Paper parity"
                value={parityShortLabel(executionParity?.comparison?.parity_label)}
                note={executionParity?.summary || "Replay/paper parity pending"}
                tone={parityTone(executionParity?.comparison?.parity_label)}
              />
            </div>
            </>
          ) : null}
        </div>

        {engineSummary?.result ? (
          <div className="mt-3.5 grid items-start gap-3.5 xl:grid-cols-3">
            <InsightCard
              title="Replay vs paper fill parity"
              subtitle="How close the historical replay execution model is to paper-trade fills"
              badgeTone={parityTone(executionParity?.comparison?.parity_label)}
              badgeLabel={executionParity?.comparison?.parity_label || executionParity?.status || "Pending"}
            >
              <div className="grid gap-2 sm:grid-cols-2">
                <MiniSummary label="Replay slip" value={formatPercent(executionParity?.backtest_model?.entry_slippage_pct, 4)} />
                <MiniSummary label="Paper avg slip" value={formatPercent(executionParity?.paper_model?.avg_entry_slippage_pct, 4)} />
                <MiniSummary label="Slip gap" value={formatPercent(executionParity?.comparison?.entry_slippage_gap_pct, 4)} />
                <MiniSummary label="RR gap" value={formatSigned(executionParity?.comparison?.risk_reward_gap, 4)} />
              </div>
              <div className="mt-2 text-xs leading-5 text-slate-400">
                {executionParity?.summary || "Parity summary will appear after replay data loads."}
              </div>
            </InsightCard>

            <InsightCard
              title="Eligibility divergence"
              subtitle="Why replay rejects trades differently from live paper-trade gating"
              badgeTone={eligibilityTone(eligibilityDivergence?.comparable_to_paper_gate?.coverage_percent)}
              badgeLabel={
                eligibilityDivergence?.comparable_to_paper_gate?.coverage_percent != null
                  ? `${formatPercent(eligibilityDivergence.comparable_to_paper_gate.coverage_percent, 0)} mapped`
                  : eligibilityDivergence?.status || "Pending"
              }
            >
              <div className="grid gap-2 sm:grid-cols-2">
                <MiniSummary label="Replay rejects" value={eligibilityDivergence?.replay_rejections?.total} />
                <MiniSummary label="Mapped to paper" value={eligibilityDivergence?.comparable_to_paper_gate?.count} />
                <MiniSummary label="Replay-only gates" value={eligibilityDivergence?.replay_only_gate?.count} />
                <MiniSummary label="Paper-only gates" value={eligibilityDivergence?.paper_only_gate?.count} />
              </div>
              <div className="mt-2 text-xs leading-5 text-slate-400">
                {eligibilityDivergence?.summary || "Divergence summary will appear after replay data loads."}
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <GateFamilyList
                  title="Replay blockers"
                  items={eligibilityDivergence?.comparable_to_paper_gate?.families}
                  emptyLabel="No comparable replay blockers"
                />
                <GateFamilyList
                  title="Paper-only requirements"
                  items={eligibilityDivergence?.paper_only_gate?.families}
                  emptyLabel="No paper-only requirements"
                />
              </div>
            </InsightCard>

            <InsightCard
              title="Point-in-time coverage"
              subtitle="How much of replay used point-in-time snapshots instead of reconstructed fallback data"
              badgeTone={coverageTone(pointInTimeCoverage)}
              badgeLabel={coverageLabel(pointInTimeCoverage)}
            >
              <div className="grid gap-2 sm:grid-cols-2">
                <MiniSummary label="Evaluated" value={pointInTimeCoverage?.evaluated_decisions} />
                <MiniSummary label="Feature hits" value={pointInTimeCoverage?.feature_snapshot_hits} />
                <MiniSummary label="Fallbacks" value={pointInTimeCoverage?.feature_reconstructed_fallbacks} />
                <MiniSummary label="Full bundle hits" value={pointInTimeCoverage?.full_point_in_time_bundle_hits} />
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <GateFamilyList
                  title="Feature leakage"
                  items={{
                    pass: pointInTimeCoverage?.feature_leakage_passes,
                    partial: pointInTimeCoverage?.feature_leakage_partials,
                    fail: pointInTimeCoverage?.feature_leakage_failures,
                  }}
                  emptyLabel="No feature leakage diagnostics"
                />
                <GateFamilyList
                  title="Thesis leakage"
                  items={{
                    pass: pointInTimeCoverage?.thesis_leakage_passes,
                    partial: pointInTimeCoverage?.thesis_leakage_partials,
                    fail: pointInTimeCoverage?.thesis_leakage_failures,
                  }}
                  emptyLabel="No thesis leakage diagnostics"
                />
              </div>
            </InsightCard>
          </div>
        ) : null}

        <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-medium text-white">Walk-forward validation</div>
              <div className="text-xs text-slate-500">
                {signalSide
                  ? `${view.symbol} ${signalSide} out-of-sample validation on ${view.timeframe || "1h"}${signalSideSource === "history" ? " (recent history fallback)" : ""}`
                  : "Choose a BUY or SELL signal on the dashboard to run walk-forward validation."}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPhase2Enabled(true)}
                disabled={!signalSide || walkForwardLoading || phase2ReportLoading}
                className="inline-flex items-center rounded-lg border border-violet-400/25 bg-violet-500/10 px-3 py-1.5 text-xs font-medium text-violet-200 transition hover:bg-violet-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {phase2Enabled ? "Phase 2 loaded" : "Load Phase 2"}
              </button>
              <Pill tone={signalSide ? "violet" : "slate"}>{signalSide || "WAIT"}</Pill>
              <Pill tone={walkForwardLoading ? "amber" : walkForwardResult?.robustness?.profitable_fold_percent >= 50 ? "emerald" : "rose"}>
                {walkForwardLoading ? "Running" : walkForwardResult?.fold_count ? `${walkForwardResult.fold_count} folds` : "Idle"}
              </Pill>
            </div>
          </div>

          {walkForwardError ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">{walkForwardError}</div> : null}
          {!phase2Enabled ? (
            <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/45 px-3 py-2 text-sm text-slate-400">
              Phase 2 validation is manual now so heavy walk-forward jobs do not slow live pages. Click <span className="font-medium text-slate-200">Load Phase 2</span> only when you want proof-of-edge analysis.
            </div>
          ) : null}

          {walkForwardResult ? (
            <>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
                <MiniSummary label="Status" value={walkForwardResult.validation_status} />
                <MiniSummary label="Folds" value={walkForwardResult.fold_count} />
                <MiniSummary label="Profitable folds" value={formatPercent(walkForwardResult.robustness?.profitable_fold_percent, 0)} />
                <MiniSummary label="OOS trades" value={walkForwardResult.out_of_sample?.total_trades} />
                <MiniSummary label="OOS return" value={formatPercent(walkForwardResult.out_of_sample?.total_return_percent, 2)} />
                <MiniSummary label="OOS PF" value={formatSigned(walkForwardResult.out_of_sample?.profit_factor, 2)} />
                <MiniSummary label="OOS win rate" value={formatPercent(walkForwardResult.out_of_sample?.win_rate, 0)} />
                <MiniSummary label="OOS drawdown" value={formatPercent(walkForwardResult.out_of_sample?.max_drawdown_percent, 2)} />
              </div>
              {validationContract ? (
                <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/55 p-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="text-sm font-medium text-white">Phase 2 contract alignment</div>
                      <div className="text-xs text-slate-500">
                        Walk-forward contract status for {validationContract.timeframe || view.timeframe || "selected"} timeframe validation.
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill tone={contractTone(validationContract.contract_status)}>{validationContract.contract_status || "Unknown"}</Pill>
                      <Pill tone={timeframeStatusTone(validationContract.timeframe_status)}>{validationContract.timeframe_status || "Unknown timeframe"}</Pill>
                    </div>
                  </div>

                  <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
                    <MiniSummary label="Contract" value={validationContract.contract_version} />
                    <MiniSummary label="Timeframe role" value={validationContract.timeframe_status} />
                    <MiniSummary label="Min folds" value={validationContract.minimum_fold_requirement} />
                    <MiniSummary label="Required candles" value={validationContract.required_candle_count_for_minimum_folds} />
                    <MiniSummary label="Config match" value={booleanContractLabel(validationContract.configuration_matches_contract)} />
                    <MiniSummary label="Target windows" value={formatContractWindows(validationContract.target_windows_days)} />
                  </div>

                  <div className="mt-2 text-xs text-slate-500">
                    Official timeframes: {(validationContract.official_timeframes || []).join(", ") || "-"}
                    {" · "}
                    Supporting timeframes: {(validationContract.supporting_timeframes || []).join(", ") || "-"}
                  </div>

                  {validationContract.issues?.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {validationContract.issues.map((issue) => (
                        <Pill key={issue} tone={issueTone(issue)}>
                          {humanizeKey(issue)}
                        </Pill>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-3 text-xs text-emerald-300">No contract issues reported.</div>
                  )}
                </div>
              ) : null}
              <div className="mt-2 text-xs text-slate-500">
                {walkForwardResult.configuration?.mode} mode · train {walkForwardResult.configuration?.train_size} / test {walkForwardResult.configuration?.test_size} / step {walkForwardResult.configuration?.step_size}
                {" · "}
                recurring best parameters: {formatSelectionCounts(walkForwardResult.robustness?.parameter_selection_counts)}
              </div>
            </>
          ) : null}
        </div>

        <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-medium text-white">Cross-scope validation trend</div>
              <div className="text-xs text-slate-500">
                Latest saved Phase 2 drift by symbol, timeframe, and side for the current signal family.
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Pill tone={signalSide ? "violet" : "slate"}>{signalSide || "WAIT"}</Pill>
              <Pill tone={phase2ScopeSummaryLoading ? "amber" : "slate"}>
                {phase2ScopeSummaryLoading ? "Loading" : `${displayedPhase2ScopeSummary.length} scopes`}
              </Pill>
            </div>
          </div>

          {phase2ScopeSummaryError ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">{phase2ScopeSummaryError}</div> : null}

          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            <Phase2LeaderboardCard
              title="Top improving"
              tone="emerald"
              item={phase2Leaderboard.topImproving}
              metricLabel="Return drift"
              metricValue={formatDriftValue(phase2Leaderboard.topImproving?.drift?.out_of_sample_total_return_percent, 2)}
              emptyLabel="No improving scope yet"
            />
            <Phase2LeaderboardCard
              title="Top deteriorating"
              tone="rose"
              item={phase2Leaderboard.topDeteriorating}
              metricLabel="Return drift"
              metricValue={formatDriftValue(phase2Leaderboard.topDeteriorating?.drift?.out_of_sample_total_return_percent, 2)}
              emptyLabel="No deteriorating scope yet"
            />
            <Phase2LeaderboardCard
              title="Best PASS"
              tone="cyan"
              item={phase2Leaderboard.bestPass}
              metricLabel="Profit factor drift"
              metricValue={formatDriftValue(phase2Leaderboard.bestPass?.drift?.out_of_sample_profit_factor, 2)}
              emptyLabel="No PASS scope in view"
            />
            <Phase2LeaderboardCard
              title="Worst FAIL"
              tone="amber"
              item={phase2Leaderboard.worstFail}
              metricLabel="Return drift"
              metricValue={formatDriftValue(phase2Leaderboard.worstFail?.drift?.out_of_sample_total_return_percent, 2)}
              emptyLabel="No FAIL scope in view"
            />
          </div>

          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {phase2SetupFamilySummary.cards.map((card) => (
              <SetupFamilyCard key={card.family} family={card.family} count={card.count} note={card.note} />
            ))}
          </div>

          <div className="mt-2 text-xs text-slate-500">
            Setup-family buckets are inferred from saved Phase 2 scope summaries, gate state, sample depth, and recent drift.
          </div>

          <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/50 p-3">
            <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Promotion-ready review view</div>
            <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
              {phase2ReviewSummary.cards.map((card) => (
                <button
                  key={card.mode}
                  type="button"
                  onClick={() => setPhase2ReviewMode(card.mode)}
                  className={`rounded-lg border px-3 py-2.5 text-left transition ${
                    phase2ReviewMode === card.mode
                      ? "border-cyan-400/40 bg-cyan-500/10"
                      : "border-white/10 bg-slate-950/50 hover:border-white/20"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{card.label}</div>
                    <Pill tone={card.tone}>{card.count}</Pill>
                  </div>
                  <div className="mt-1 text-xs leading-5 text-slate-400">{card.note}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="mt-3 grid gap-2 md:grid-cols-3">
            <FilterSelect
              label="Timeframe"
              value={phase2ScopeTimeframeFilter}
              onChange={setPhase2ScopeTimeframeFilter}
              options={[
                { value: "ALL", label: "All timeframes" },
                ...phase2ScopeTimeframeOptions.map((value) => ({ value, label: value })),
              ]}
            />
            <FilterSelect
              label="Status"
              value={phase2ScopeStatusFilter}
              onChange={setPhase2ScopeStatusFilter}
              options={[
                { value: "ALL", label: "All statuses" },
                { value: "PASS", label: "PASS" },
                { value: "PARTIAL", label: "PARTIAL" },
                { value: "FAIL", label: "FAIL" },
                { value: "INSUFFICIENT_EVIDENCE", label: "INSUFFICIENT_EVIDENCE" },
              ]}
            />
            <FilterSelect
              label="Sort"
              value={phase2ScopeSort}
              onChange={setPhase2ScopeSort}
              options={[
                { value: "LATEST", label: "Latest saved" },
                { value: "BEST_RETURN", label: "Best return drift" },
                { value: "WORST_RETURN", label: "Worst return drift" },
                { value: "BEST_PF", label: "Best PF drift" },
                { value: "WORST_DD", label: "Worst drawdown drift" },
                { value: "MOST_SAMPLES", label: "Most samples" },
              ]}
            />
          </div>

          <div className="mt-3 grid gap-2 xl:grid-cols-2">
            {displayedPhase2ScopeSummary.length ? (
              displayedPhase2ScopeSummary.map((item) => (
                <div key={item.artifact_id || `${item.scope?.symbol}-${item.scope?.timeframe}-${item.scope?.signal}`} className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium text-white">
                      {item.scope?.symbol || "-"} · {item.scope?.timeframe || "-"} · {item.scope?.signal || "-"}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Pill tone={phase2ReportTone(item.overall_status)}>{item.overall_status || "Unknown"}</Pill>
                      <Pill tone={statusChangeTone(item.status_change)}>{humanizeStatusChange(item.status_change)}</Pill>
                    </div>
                  </div>

                  <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                    <MiniSummary label="Samples" value={item.sample_count} />
                    <MiniSummary label="Return drift" value={formatDriftValue(item.drift?.out_of_sample_total_return_percent, 2)} />
                    <MiniSummary label="PF drift" value={formatDriftValue(item.drift?.out_of_sample_profit_factor, 2)} />
                    <MiniSummary label="DD drift" value={formatDriftValue(item.drift?.out_of_sample_max_drawdown_percent, 2)} />
                  </div>

                  <div className="mt-2 text-xs text-slate-400">
                    Latest saved: {formatDate(item.saved_at, item.saved_at)}
                    {item.previous_saved_at ? ` · Previous: ${formatDate(item.previous_saved_at, item.previous_saved_at)}` : ""}
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-white/10 bg-slate-950/40 px-3 py-3 text-sm text-slate-500">
                {(filteredPhase2ScopeSummary || []).length
                  ? "No records match the current review mode."
                  : (phase2ScopeSummary || []).length
                    ? "No records match the current filter."
                  : "No cross-scope Phase 2 summary records yet."}
              </div>
            )}
          </div>
        </div>

        <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-medium text-white">Phase 2 validation report</div>
              <div className="text-xs text-slate-500">
                Formal proof-of-edge status derived from walk-forward output and current architecture gate coverage.
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Pill tone={signalSide ? "violet" : "slate"}>{signalSide || "WAIT"}</Pill>
              <Pill tone={phase2ReportLoading ? "amber" : phase2ReportTone(phase2Report?.overall_status)}>
                {phase2ReportLoading ? "Building" : phase2Report?.overall_status || "Idle"}
              </Pill>
              <button
                type="button"
                onClick={handleExportPhase2Report}
                disabled={phase2ExportLoading || !signalSide || !phase2Enabled}
                className="inline-flex items-center rounded-lg border border-cyan-400/25 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {phase2ExportLoading ? "Exporting..." : "Export report"}
              </button>
            </div>
          </div>

          {phase2ReportError ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">{phase2ReportError}</div> : null}
          {phase2ExportError ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">{phase2ExportError}</div> : null}
          {phase2Report?.promotion_allowed === false ? (
            <div className="mt-3 rounded-lg border border-amber-400/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
              <div className="font-medium">R0 truth-repair lock · {phase2Report.evidence_status || "Research only"}</div>
              <div className="mt-1 text-xs leading-5 text-amber-200/85">
                Historical metrics remain visible for diagnosis, but this evidence cannot be promoted until canonical final candles and full replay parity are rebuilt.
              </div>
            </div>
          ) : null}
          {phase2ExportResult ? (
            <div className="mt-3 rounded-lg border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">
              Saved Phase 2 artifact.
              <div className="mt-1 text-xs text-emerald-200/90">JSON: {phase2ExportResult.json_path}</div>
              <div className="mt-1 text-xs text-emerald-200/90">Markdown: {phase2ExportResult.markdown_path}</div>
            </div>
          ) : null}

          {phase2Report ? (
            <>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
                <MiniSummary label="Overall" value={phase2Report.overall_status} />
                <MiniSummary label="Gate" value={phase2Report.architecture_gate?.status} />
                <MiniSummary label="Passed checks" value={phase2Report.architecture_gate?.passed_checks} />
                <MiniSummary label="Missing checks" value={phase2Report.architecture_gate?.unavailable_checks} />
                <MiniSummary label="OOS trades" value={phase2Report.derived_metrics?.out_of_sample_total_trades} />
                <MiniSummary label="OOS payoff" value={formatSigned(phase2Report.derived_metrics?.out_of_sample_payoff_ratio, 2)} />
                <MiniSummary label="Trade Sharpe" value={formatSigned(phase2Report.derived_metrics?.trade_return_sharpe, 2)} />
                <MiniSummary label="Next action" value={shortNextAction(phase2Report.next_action)} />
              </div>

              {promotionScorecard ? (
                <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/55 p-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="text-sm font-medium text-white">Promotion scorecard</div>
                      <div className="text-xs text-slate-500">
                        Practical Phase 2 grading for promotion-candidate review.
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill tone={promotionScorecardTone(promotionScorecard.decision)}>{promotionScorecard.decision}</Pill>
                      <Pill tone={promotionScorecard.score >= 5 ? "emerald" : promotionScorecard.score >= 3.5 ? "amber" : "rose"}>
                        {promotionScorecard.scoreLabel}
                      </Pill>
                    </div>
                  </div>

                  <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
                    {promotionScorecard.items.map((item) => (
                      <div key={item.key} className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-[11px] font-medium text-slate-200">{item.label}</div>
                          <Pill tone={promotionItemTone(item.status)}>{item.status}</Pill>
                        </div>
                        <div className="mt-1 text-xs text-slate-400">
                          Actual: {item.actualLabel} / Target: {item.targetLabel}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">{item.pointsLabel}</div>
                      </div>
                    ))}
                  </div>

                  <div className="mt-2 text-xs leading-5 text-slate-400">
                    {promotionScorecard.summary}
                  </div>
                </div>
              ) : null}

              {phase3EntryGate ? (
                <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/55 p-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="text-sm font-medium text-white">Phase 3 entry gate</div>
                      <div className="text-xs text-slate-500">
                        Explicit promotion rule for controlled execution-readiness entry.
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill tone={phase3GateTone(phase3EntryGate.status)}>{phase3EntryGate.status}</Pill>
                      <Pill tone={phase3EntryGate.passedChecks === phase3EntryGate.totalChecks ? "emerald" : phase3EntryGate.passedChecks >= Math.ceil(phase3EntryGate.totalChecks / 2) ? "amber" : "rose"}>
                        {phase3EntryGate.passedChecks}/{phase3EntryGate.totalChecks} checks
                      </Pill>
                    </div>
                  </div>

                  <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {phase3EntryGate.checks.map((check) => (
                      <div key={check.key} className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-[11px] font-medium text-slate-200">{check.label}</div>
                          <Pill tone={phase3GateCheckTone(check.status)}>{check.status}</Pill>
                        </div>
                        <div className="mt-1 text-xs text-slate-400">
                          Actual: {check.actualLabel} / Target: {check.targetLabel}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    {phase3EntryGate.blockers.length ? (
                      phase3EntryGate.blockers.map((blocker) => (
                        <Pill key={blocker} tone="amber">{blocker}</Pill>
                      ))
                    ) : (
                      <Pill tone="emerald">No Phase 3 blockers</Pill>
                    )}
                  </div>

                  <div className="mt-2 text-xs leading-5 text-slate-400">
                    {phase3EntryGate.summary}
                  </div>
                </div>
              ) : null}

              <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/55 p-3">
                <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Architecture gate checks</div>
                <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {(phase2Report.architecture_gate?.checks || []).map((check) => (
                    <div key={check.name} className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-xs font-medium text-slate-200">{humanizeKey(check.name)}</div>
                        <Pill tone={phase2CheckTone(check.status)}>{check.status}</Pill>
                      </div>
                      <div className="mt-1 text-xs text-slate-400">
                        Actual: {formatCheckActual(check.actual)} · Target: {formatCheckTarget(check.threshold, check.comparison)}
                      </div>
                      {check.note ? <div className="mt-1 text-xs leading-5 text-slate-500">{check.note}</div> : null}
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {(phase2Report.blocked_by || []).length ? (
                  phase2Report.blocked_by.map((blocker) => (
                    <Pill key={blocker} tone="amber">{humanizeKey(blocker)}</Pill>
                  ))
                ) : (
                  <Pill tone="emerald">No active validation blockers</Pill>
                )}
              </div>

              <div className="mt-2 text-xs leading-5 text-slate-400">{phase2Report.next_action || "No next action provided."}</div>
            </>
          ) : null}
        </div>

        <div className="mt-3.5 rounded-lg border border-white/10 bg-slate-900/70 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-medium text-white">Saved validation artifacts</div>
              <div className="text-xs text-slate-500">
                Recent exported Phase 2 reports for this symbol, timeframe, and side.
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Pill tone={phase2HistoryLoading ? "amber" : "slate"}>
                {phase2HistoryLoading ? "Loading" : `${phase2History.length} saved`}
              </Pill>
            </div>
          </div>

          {phase2HistoryError ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">{phase2HistoryError}</div> : null}

          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            {(phase2History || []).length ? (
              phase2History.map((item) => (
                <div key={item.artifact_id || item.json_path} className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium text-white">{item.scope?.symbol || view.symbol} · {item.scope?.timeframe || view.timeframe} · {item.scope?.signal || signalSide}</div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill tone={phase2ReportTone(item.overall_status)}>{item.overall_status || "Unknown"}</Pill>
                      <Pill tone={phase2ReportTone(item.architecture_gate_status)}>{item.architecture_gate_status || "Unknown gate"}</Pill>
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-slate-400">{formatDate(item.saved_at, item.saved_at)}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => handleLoadArtifact(item.artifact_id)}
                      className="inline-flex items-center rounded-lg border border-cyan-400/25 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/20"
                    >
                      Load artifact
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-white/10 bg-slate-950/40 px-3 py-3 text-sm text-slate-500">
                No saved Phase 2 validation artifacts yet for this scope.
              </div>
            )}
          </div>

          {selectedArtifactError ? <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">{selectedArtifactError}</div> : null}

          {selectedArtifactLoading ? (
            <div className="mt-3 text-sm text-amber-200">Loading saved artifact...</div>
          ) : null}

          {selectedArtifact?.payload?.report ? (
            <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/55 p-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-sm font-medium text-white">Loaded saved artifact</div>
                  <div className="text-xs text-slate-500">
                    {selectedArtifact.payload.scope?.symbol} · {selectedArtifact.payload.scope?.timeframe} · {selectedArtifact.payload.scope?.signal}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Pill tone={phase2ReportTone(selectedArtifact.payload.report?.overall_status)}>{selectedArtifact.payload.report?.overall_status || "Unknown"}</Pill>
                  <Pill tone="slate">{selectedArtifact.artifact?.artifact_id || "artifact"}</Pill>
                </div>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                <MiniSummary label="Saved at" value={formatDate(selectedArtifact.payload.saved_at, selectedArtifact.payload.saved_at)} />
                <MiniSummary label="Gate" value={selectedArtifact.payload.report?.architecture_gate?.status} />
                <MiniSummary label="OOS trades" value={selectedArtifact.payload.report?.derived_metrics?.out_of_sample_total_trades} />
                <MiniSummary label="Next action" value={shortNextAction(selectedArtifact.payload.report?.next_action)} />
              </div>
            </div>
          ) : null}

          {phase2Report && selectedArtifact?.payload?.report ? (
            <div className="mt-3 rounded-lg border border-white/10 bg-slate-950/55 p-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-sm font-medium text-white">Current vs saved comparison</div>
                  <div className="text-xs text-slate-500">
                    Compare the live Phase 2 report with the selected saved artifact.
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Pill tone={phase2ReportTone(phase2Report.overall_status)}>{phase2Report.overall_status || "Current"}</Pill>
                  <Pill tone="slate">vs</Pill>
                  <Pill tone={phase2ReportTone(selectedArtifact.payload.report?.overall_status)}>{selectedArtifact.payload.report?.overall_status || "Saved"}</Pill>
                </div>
              </div>

              <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {buildPhase2ComparisonRows(phase2Report, selectedArtifact.payload.report).map((row) => (
                  <div key={row.label} className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs font-medium text-slate-200">{row.label}</div>
                      <Pill tone={row.tone}>{row.deltaLabel}</Pill>
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      Current: {row.currentLabel}
                      {" · "}
                      Saved: {row.savedLabel}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="mt-3.5 grid items-start gap-3.5 xl:grid-cols-[1.3fr_0.7fr]">
          <ChartCard title="Equity curve" subtitle="Cumulative closed trade PNL">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={displayedEquitySeries}>
                <defs>
                  <linearGradient id="backtestEquityFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#22d3ee" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value), "Equity"]} />
                <Area type="monotone" dataKey="equity" stroke="#22d3ee" fill="url(#backtestEquityFill)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Win / loss" subtitle="Closed trade outcomes">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={winLossSeries} dataKey="value" nameKey="name" innerRadius={52} outerRadius={86}>
                  <Cell fill="#34d399" />
                  <Cell fill="#fb7185" />
                </Pie>
                <Tooltip contentStyle={tooltipStyle()} />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <div className="mt-3.5 grid items-start gap-3.5 xl:grid-cols-2">
          <ChartCard title="Daily PNL" subtitle="Closed PNL grouped by close date">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dailySeries}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value), "Daily PNL"]} />
                <Bar dataKey="pnl" radius={[6, 6, 0, 0]}>
                  {dailySeries.map((item) => (
                    <Cell key={item.label} fill={item.pnl >= 0 ? "#34d399" : "#fb7185"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Drawdown" subtitle="Peak-to-trough drift from equity high">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={drawdownSeries}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value), "Drawdown"]} />
                <Line type="monotone" dataKey="drawdown" stroke="#fb7185" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <div className="mt-3.5 grid items-start gap-3.5 xl:grid-cols-[0.9fr_1.1fr]">
          <ChartCard title="PNL by symbol" subtitle="Closed trade contribution">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={displayedPnlBySymbol} layout="vertical">
                <CartesianGrid stroke="rgba(148,163,184,0.12)" horizontal={false} />
                <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 11 }} />
                <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "#cbd5e1", fontSize: 11 }} width={80} />
                <Tooltip contentStyle={tooltipStyle()} formatter={(value) => [formatSigned(value), "PNL"]} />
                <Bar dataKey="value" radius={[0, 8, 8, 0]}>
                  {displayedPnlBySymbol.map((entry, index) => (
                    <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          <BacktestTrades tradeHistory={displayTradeHistory} symbol={view.symbol} />
        </div>

        {engineSummary?.result?.trades?.length ? (
          <div className="mt-3.5 overflow-hidden rounded-lg border border-white/10 bg-slate-900/70 p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">Engine trades</div>
                <div className="text-xs text-slate-500">Latest simulated trades from the backtest engine</div>
              </div>
              <Pill tone="cyan">{engineSummary.result.trades.length} samples</Pill>
            </div>
            <div className="mt-2.5 overflow-x-auto">
              <table className="min-w-full divide-y divide-white/5 text-sm">
                <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                  <tr>
                    <th className="px-3 py-2.5 text-left">Entry</th>
                    <th className="px-3 py-2.5 text-left">Stop</th>
                    <th className="px-3 py-2.5 text-left">Target</th>
                    <th className="px-3 py-2.5 text-left">PnL</th>
                    <th className="px-3 py-2.5 text-left">Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {engineSummary.result.trades.slice(0, 10).map((trade, index) => (
                    <tr key={`${trade.entry}-${index}`} className="bg-slate-950/35">
                      <td className="px-3 py-2.5 text-slate-300">{formatSigned(trade.entry, 2, "-")}</td>
                      <td className="px-3 py-2.5 text-slate-300">{formatSigned(trade.stop, 2, "-")}</td>
                      <td className="px-3 py-2.5 text-slate-300">{formatSigned(trade.target, 2, "-")}</td>
                      <td className={trade.pnl >= 0 ? "px-3 py-2.5 font-medium text-emerald-300" : "px-3 py-2.5 font-medium text-rose-300"}>
                        {formatSigned(trade.pnl, 2, "-")}
                      </td>
                      <td className="px-3 py-2.5 text-slate-300">{trade.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{title}</div>
          <div className="text-xs text-slate-500">{subtitle}</div>
        </div>
      </div>
      <div className="h-60">{children}</div>
    </div>
  );
}

function InsightCard({ title, subtitle, badgeLabel, badgeTone = "slate", children }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{title}</div>
          <div className="text-xs leading-5 text-slate-500">{subtitle}</div>
        </div>
        {badgeLabel ? <Pill tone={badgeTone}>{badgeLabel}</Pill> : null}
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function DiagnosticStrip({ label, value, note, tone = "slate" }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
        <Pill tone={tone}>{value ?? "-"}</Pill>
      </div>
      <div className="mt-1.5 text-xs leading-5 text-slate-400">{note || "-"}</div>
    </div>
  );
}

function GateFamilyList({ title, items, emptyLabel }) {
  const entries = normalizeFamilyEntries(items);

  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/40 p-2.5">
      <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{title}</div>
      <div className="mt-2 space-y-2">
        {entries.length ? (
          entries.map(([key, value]) => (
            <div key={key} className="rounded-lg border border-white/5 bg-slate-950/50 px-2.5 py-2">
              <div className="text-xs font-medium text-slate-200">{humanizeKey(key)}</div>
              <div className="mt-1 text-xs leading-5 text-slate-400">{formatFamilyValue(value)}</div>
            </div>
          ))
        ) : (
          <div className="text-xs text-slate-500">{emptyLabel}</div>
        )}
      </div>
    </div>
  );
}

function BacktestTrades({ tradeHistory, symbol }) {
  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-slate-900/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">Replay samples</div>
          <div className="text-xs text-slate-500">Most recent closed trades</div>
        </div>
        <Pill tone="slate">{tradeHistory.length} closed</Pill>
      </div>
      <div className="mt-2.5 overflow-x-auto">
        <table className="min-w-full divide-y divide-white/5 text-sm">
          <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            <tr>
              <th className="px-3 py-2.5 text-left">Symbol</th>
              <th className="px-3 py-2.5 text-left">Side</th>
              <th className="px-3 py-2.5 text-left">PNL</th>
              <th className="px-3 py-2.5 text-left">Result</th>
              <th className="px-3 py-2.5 text-left">Closed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {tradeHistory.slice(0, 10).map((trade, index) => (
              <tr key={trade.id || trade.entry_time || trade.closed_at || index} className="bg-slate-950/35">
                <td className="px-3 py-2.5 text-white">{trade.symbol || symbol}</td>
                <td className="px-3 py-2.5 text-slate-300">{trade.side}</td>
                <td className={tradePnlValue(trade) >= 0 ? "px-3 py-2.5 font-medium text-emerald-300" : "px-3 py-2.5 font-medium text-rose-300"}>
                  {formatSigned(tradePnlValue(trade))}
                </td>
                <td className="px-3 py-2.5 text-slate-300">{trade.result || "N/A"}</td>
                <td className="px-3 py-2.5 text-slate-400">{formatDate(trade.closed_at || trade.exit_time || trade.created_at || trade.entry_time)}</td>
              </tr>
            ))}
            {!tradeHistory.length ? (
              <tr>
                <td className="px-3 py-3.5 text-slate-400" colSpan={5}>
                  No closed trades available for replay.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function buildDailyPnlSeries(trades) {
  const groups = new Map();

  trades.forEach((trade) => {
    const date = new Date(trade.closed_at || trade.exit_time || trade.created_at || trade.entry_time || 0);
    const key = Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 10) : "Unknown";
    groups.set(key, (groups.get(key) || 0) + tradePnlValue(trade));
  });

  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, pnl]) => ({ label: label.slice(5), pnl: Number(pnl.toFixed(2)) }));
}

function buildDrawdownSeries(series) {
  let peak = -Infinity;

  return series.map((point) => {
    peak = Math.max(peak, safeNumber(point.equity, 0));
    return {
      label: point.label,
      drawdown: Number((safeNumber(point.equity, 0) - peak).toFixed(2)),
    };
  });
}

function calculateExpectancy(trades) {
  if (!trades.length) return 0;
  return Number((trades.reduce((sum, trade) => sum + tradePnlValue(trade), 0) / trades.length).toFixed(2));
}

function deriveBacktestSignalSide(signalType, symbol, tradeHistory = []) {
  const direct = signalSideForBacktest(signalType);
  if (direct) {
    return { signalSide: direct, signalSideSource: "signal" };
  }

  const fallbackTrade = (tradeHistory || []).find((trade) => String(trade?.symbol || "").toUpperCase() === String(symbol || "").toUpperCase());
  const fallbackSide = normalizeBacktestTradeSide(fallbackTrade?.side);

  return {
    signalSide: fallbackSide,
    signalSideSource: fallbackSide ? "history" : null,
  };
}

function signalSideForBacktest(signalType) {
  if (signalType === "BUY") return "LONG";
  if (signalType === "SELL") return "SHORT";
  return null;
}

function normalizeBacktestTradeSide(side) {
  const normalized = String(side || "").toUpperCase();
  if (normalized === "BUY") return "LONG";
  if (normalized === "SELL") return "SHORT";
  if (normalized === "LONG" || normalized === "SHORT") return normalized;
  return null;
}

function MiniSummary({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/70 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-white">{value ?? "-"}</div>
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-white/10 bg-slate-950/80 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-cyan-400/40"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function Phase2LeaderboardCard({ title, tone, item, metricLabel, metricValue, emptyLabel }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{title}</div>
        <Pill tone={tone}>{item?.overall_status || "N/A"}</Pill>
      </div>
      {item ? (
        <>
          <div className="mt-2 text-sm font-medium text-white">{formatPhase2ScopeLabel(item)}</div>
          <div className="mt-1 text-xs text-slate-400">{metricLabel}: {metricValue}</div>
          <div className="mt-1 text-xs text-slate-500">
            Samples: {item.sample_count ?? "-"} / Saved: {formatDate(item.saved_at, item.saved_at)}
          </div>
        </>
      ) : (
        <div className="mt-2 text-sm text-slate-500">{emptyLabel}</div>
      )}
    </div>
  );
}

function SetupFamilyCard({ family, count, note }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{humanizeSetupFamily(family)}</div>
        <Pill tone={setupFamilyTone(family)}>{count}</Pill>
      </div>
      <div className="mt-1 text-xs leading-5 text-slate-400">{note}</div>
    </div>
  );
}

function promotionScorecardTone(value) {
  if (value === "PROMOTION_CANDIDATE") return "emerald";
  if (value === "VALIDATION_WATCHLIST") return "amber";
  return "rose";
}

function promotionItemTone(value) {
  if (value === "PASS") return "emerald";
  if (value === "WATCH") return "amber";
  return "rose";
}

function phase3GateTone(value) {
  if (value === "READY_FOR_PHASE3") return "emerald";
  if (value === "PHASE2_WATCHLIST") return "amber";
  return "rose";
}

function phase3GateCheckTone(value) {
  if (value === "PASS") return "emerald";
  if (value === "WATCH") return "amber";
  return "rose";
}

function setupFamilyTone(value) {
  if (value === "PROMOTION_CANDIDATE") return "emerald";
  if (value === "VALIDATION_WATCHLIST") return "amber";
  if (value === "PAPER_ONLY") return "cyan";
  return "rose";
}

function humanizeSetupFamily(value) {
  if (value === "PAPER_ONLY") return "Paper only";
  if (value === "VALIDATION_WATCHLIST") return "Validation watchlist";
  if (value === "PROMOTION_CANDIDATE") return "Promotion candidate";
  return "Blocked";
}

function contractTone(status) {
  if (status === "PASS") return "emerald";
  if (status === "PARTIAL" || status === "INSUFFICIENT_EVIDENCE") return "amber";
  if (status === "FAIL") return "rose";
  return "slate";
}

function phase2ReportTone(status) {
  if (status === "PASS") return "emerald";
  if (status === "FAIL") return "rose";
  if (status === "PARTIAL" || status === "INSUFFICIENT_EVIDENCE") return "amber";
  return "slate";
}

function phase2CheckTone(status) {
  if (status === "PASS") return "emerald";
  if (status === "FAIL") return "rose";
  if (status === "NOT_STARTED" || status === "INSUFFICIENT_EVIDENCE") return "amber";
  return "slate";
}

function timeframeStatusTone(status) {
  if (status === "OFFICIAL") return "emerald";
  if (status === "SUPPORTING") return "amber";
  return "slate";
}

function issueTone(issue) {
  if (issue === "minimum_fold_requirement_not_met" || issue === "insufficient_history_for_phase2_fold_requirement") {
    return "amber";
  }
  if (issue === "walk_forward_windows_do_not_match_phase2_contract") {
    return "rose";
  }
  return "slate";
}

function booleanContractLabel(value) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "N/A";
}

function formatContractWindows(windows) {
  if (!windows) return "-";
  const train = safeNumber(windows.train_window_days, 0);
  const test = safeNumber(windows.test_window_days, 0);
  const step = safeNumber(windows.step_days, 0);
  return `${train}d / ${test}d / ${step}d`;
}

function formatCheckActual(actual) {
  if (actual === null || actual === undefined) return "N/A";
  if (typeof actual === "number") return formatSigned(actual, 2);
  return String(actual);
}

function formatCheckTarget(threshold, comparison) {
  if (threshold === null || threshold === undefined) return "N/A";
  const prefix = comparison === "maximum" ? "≤" : comparison === "minimum" ? "≥" : "";
  return `${prefix}${threshold}`;
}

function shortNextAction(value) {
  if (!value) return "-";
  if (value.length <= 42) return value;
  return `${value.slice(0, 39)}...`;
}

function buildPhase2ComparisonRows(currentReport, savedReport) {
  return [
    compareMetricRow("Overall status", currentReport?.overall_status, savedReport?.overall_status, { kind: "status" }),
    compareMetricRow("Architecture gate", currentReport?.architecture_gate?.status, savedReport?.architecture_gate?.status, { kind: "status" }),
    compareMetricRow(
      "OOS trades",
      currentReport?.derived_metrics?.out_of_sample_total_trades,
      savedReport?.derived_metrics?.out_of_sample_total_trades,
      { kind: "number", digits: 0 }
    ),
    compareMetricRow(
      "OOS return %",
      currentReport?.derived_metrics?.out_of_sample_total_return_percent,
      savedReport?.derived_metrics?.out_of_sample_total_return_percent,
      { kind: "number", digits: 2, better: "higher" }
    ),
    compareMetricRow(
      "OOS profit factor",
      currentReport?.derived_metrics?.out_of_sample_profit_factor,
      savedReport?.derived_metrics?.out_of_sample_profit_factor,
      { kind: "number", digits: 2, better: "higher" }
    ),
    compareMetricRow(
      "OOS win rate",
      currentReport?.derived_metrics?.out_of_sample_win_rate,
      savedReport?.derived_metrics?.out_of_sample_win_rate,
      { kind: "number", digits: 2, better: "higher" }
    ),
    compareMetricRow(
      "OOS drawdown %",
      currentReport?.derived_metrics?.out_of_sample_max_drawdown_percent,
      savedReport?.derived_metrics?.out_of_sample_max_drawdown_percent,
      { kind: "number", digits: 2, better: "lower" }
    ),
    compareMetricRow(
      "OOS payoff ratio",
      currentReport?.derived_metrics?.out_of_sample_payoff_ratio,
      savedReport?.derived_metrics?.out_of_sample_payoff_ratio,
      { kind: "number", digits: 2, better: "higher" }
    ),
  ].filter(Boolean);
}

function compareMetricRow(label, currentValue, savedValue, options = {}) {
  const { kind = "number", digits = 2, better = "higher" } = options;
  if (kind === "status") {
    const unchanged = String(currentValue || "-") === String(savedValue || "-");
    return {
      label,
      currentLabel: String(currentValue || "-"),
      savedLabel: String(savedValue || "-"),
      deltaLabel: unchanged ? "Unchanged" : "Changed",
      tone: unchanged ? "slate" : "amber",
    };
  }

  const current = parseOptionalNumber(currentValue);
  const saved = parseOptionalNumber(savedValue);
  const delta = current !== null && saved !== null ? current - saved : null;
  const unchanged = delta === null ? false : Math.abs(delta) < 0.000001;
  return {
    label,
    currentLabel: formatCompareNumber(current, digits),
    savedLabel: formatCompareNumber(saved, digits),
    deltaLabel: delta === null ? "N/A" : unchanged ? "Flat" : `${delta > 0 ? "+" : ""}${delta.toFixed(digits)}`,
    tone: deltaTone(delta, better),
  };
}

function deltaTone(delta, better) {
  if (delta === null) return "slate";
  if (Math.abs(delta) < 0.000001) return "slate";
  if (better === "lower") {
    return delta < 0 ? "emerald" : "rose";
  }
  return delta > 0 ? "emerald" : "rose";
}

function parseOptionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatCompareNumber(value, digits) {
  if (value === null) return "N/A";
  return Number(value).toFixed(digits);
}

function formatDriftValue(value, digits = 2) {
  const parsed = parseOptionalNumber(value);
  if (parsed === null) return "N/A";
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(digits)}`;
}

function formatPhase2ScopeLabel(item) {
  return [item?.scope?.symbol || "-", item?.scope?.timeframe || "-", item?.scope?.signal || "-"].join(" / ");
}

function buildPhase2Leaderboard(records) {
  const items = Array.isArray(records) ? [...records] : [];
  const byReturnDesc = [...items].sort((left, right) => compareOptionalNumberDesc(
    left?.drift?.out_of_sample_total_return_percent,
    right?.drift?.out_of_sample_total_return_percent,
    left?.saved_at,
    right?.saved_at
  ));
  const byReturnAsc = [...items].sort((left, right) => compareOptionalNumberAsc(
    left?.drift?.out_of_sample_total_return_percent,
    right?.drift?.out_of_sample_total_return_percent,
    left?.saved_at,
    right?.saved_at
  ));
  const passing = items.filter((item) => item?.overall_status === "PASS");
  const failing = items.filter((item) => item?.overall_status === "FAIL");
  const bestPass = [...passing].sort((left, right) => compareOptionalNumberDesc(
    left?.drift?.out_of_sample_profit_factor,
    right?.drift?.out_of_sample_profit_factor,
    left?.saved_at,
    right?.saved_at
  ))[0] || null;
  const worstFail = [...failing].sort((left, right) => compareOptionalNumberAsc(
    left?.drift?.out_of_sample_total_return_percent,
    right?.drift?.out_of_sample_total_return_percent,
    left?.saved_at,
    right?.saved_at
  ))[0] || null;

  return {
    topImproving: byReturnDesc[0] || null,
    topDeteriorating: byReturnAsc[0] || null,
    bestPass,
    worstFail,
  };
}

function buildPhase2SetupFamilySummary(records) {
  const classified = (Array.isArray(records) ? records : []).map(classifyPhase2SetupFamily);
  const counts = classified.reduce((accumulator, item) => {
    accumulator[item.family] = (accumulator[item.family] || 0) + 1;
    return accumulator;
  }, {
    BLOCKED: 0,
    PAPER_ONLY: 0,
    VALIDATION_WATCHLIST: 0,
    PROMOTION_CANDIDATE: 0,
  });

  return {
    counts,
    cards: [
      {
        family: "BLOCKED",
        count: counts.BLOCKED,
        note: "Fails edge quality or gate quality right now.",
      },
      {
        family: "PAPER_ONLY",
        count: counts.PAPER_ONLY,
        note: "Needs more evidence before it can be judged for promotion.",
      },
      {
        family: "VALIDATION_WATCHLIST",
        count: counts.VALIDATION_WATCHLIST,
        note: "Worth watching closely, but not yet ready to promote.",
      },
      {
        family: "PROMOTION_CANDIDATE",
        count: counts.PROMOTION_CANDIDATE,
        note: "Strongest current scopes under the saved Phase 2 summary.",
      },
    ],
  };
}

function buildPhase2ReviewSummary(records) {
  const items = Array.isArray(records) ? records : [];
  return {
    cards: [
      {
        mode: "ALL",
        label: "All scopes",
        count: items.length,
        tone: "slate",
        note: "Everything in the current filtered Phase 2 view.",
      },
      {
        mode: "PROMOTION_CANDIDATES",
        label: "Promotion candidates",
        count: items.filter((item) => classifyPhase2SetupFamily(item).family === "PROMOTION_CANDIDATE").length,
        tone: "emerald",
        note: "Best current scopes for promotion review.",
      },
      {
        mode: "UNSTABLE",
        label: "Unstable setups",
        count: items.filter(isPhase2Unstable).length,
        tone: "rose",
        note: "Failing or sharply deteriorating scopes.",
      },
      {
        mode: "IMPROVING",
        label: "Recently improved",
        count: items.filter(isPhase2Improving).length,
        tone: "cyan",
        note: "Scopes with encouraging recent drift.",
      },
      {
        mode: "DETERIORATING",
        label: "Recently degraded",
        count: items.filter(isPhase2Deteriorating).length,
        tone: "amber",
        note: "Scopes trending the wrong way recently.",
      },
    ],
  };
}

function matchesPhase2ReviewMode(item, mode) {
  if (mode === "PROMOTION_CANDIDATES") return classifyPhase2SetupFamily(item).family === "PROMOTION_CANDIDATE";
  if (mode === "UNSTABLE") return isPhase2Unstable(item);
  if (mode === "IMPROVING") return isPhase2Improving(item);
  if (mode === "DETERIORATING") return isPhase2Deteriorating(item);
  return true;
}

function isPhase2Improving(item) {
  const returnDrift = parseOptionalNumber(item?.drift?.out_of_sample_total_return_percent);
  const pfDrift = parseOptionalNumber(item?.drift?.out_of_sample_profit_factor);
  return (returnDrift !== null && returnDrift > 0) || (pfDrift !== null && pfDrift > 0);
}

function isPhase2Deteriorating(item) {
  const returnDrift = parseOptionalNumber(item?.drift?.out_of_sample_total_return_percent);
  const pfDrift = parseOptionalNumber(item?.drift?.out_of_sample_profit_factor);
  return (returnDrift !== null && returnDrift < 0) || (pfDrift !== null && pfDrift < 0);
}

function isPhase2Unstable(item) {
  const setupFamily = classifyPhase2SetupFamily(item).family;
  const drawdownDrift = parseOptionalNumber(item?.drift?.out_of_sample_max_drawdown_percent);
  return setupFamily === "BLOCKED" || setupFamily === "PAPER_ONLY" || (drawdownDrift !== null && drawdownDrift > 0);
}

function classifyPhase2SetupFamily(item) {
  if (item?.promotion_allowed === false || String(item?.evidence_status || "").includes("INVALIDATED")) {
    return { family: "PAPER_ONLY" };
  }

  const overallStatus = String(item?.overall_status || "").toUpperCase();
  const gateStatus = String(item?.architecture_gate_status || "").toUpperCase();
  const sampleCount = safeNumber(item?.sample_count, 0);
  const returnDrift = parseOptionalNumber(item?.drift?.out_of_sample_total_return_percent);
  const pfDrift = parseOptionalNumber(item?.drift?.out_of_sample_profit_factor);

  if (overallStatus === "FAIL" || gateStatus === "FAIL") {
    return { family: "BLOCKED" };
  }

  if (
    overallStatus === "PASS"
    && gateStatus === "PASS"
    && sampleCount >= 2
    && (returnDrift === null || returnDrift >= 0)
    && (pfDrift === null || pfDrift >= 0)
  ) {
    return { family: "PROMOTION_CANDIDATE" };
  }

  if (
    (overallStatus === "PASS" || overallStatus === "PARTIAL")
    && sampleCount >= 1
    && (returnDrift === null || returnDrift > -2)
  ) {
    return { family: "VALIDATION_WATCHLIST" };
  }

  if (
    overallStatus === "INSUFFICIENT_EVIDENCE"
    || gateStatus === "INSUFFICIENT_EVIDENCE"
    || overallStatus === "PARTIAL"
  ) {
    return { family: "PAPER_ONLY" };
  }

  return { family: "BLOCKED" };
}

function buildPromotionScorecard(report, walkForwardResult) {
  if (!report) return null;

  const metrics = report?.derived_metrics || {};
  const gateChecks = report?.architecture_gate?.checks || [];
  const foldCount = safeNumber(report?.walk_forward?.fold_count, 0);
  const minimumFolds = safeNumber(report?.walk_forward?.contract?.minimum_fold_requirement, 0);
  const profitableFoldPercent = safeNumber(walkForwardResult?.robustness?.profitable_fold_percent, null);
  const contractStatus = report?.walk_forward?.contract?.contract_status || "UNKNOWN";
  const gateStatus = report?.architecture_gate?.status || "UNKNOWN";
  const promotionAllowed = report?.promotion_allowed !== false;

  const items = [
    buildPromotionItem({
      key: "oos_return",
      label: "OOS return",
      actual: metrics.out_of_sample_total_return_percent,
      actualLabel: formatPercent(metrics.out_of_sample_total_return_percent, 2),
      targetLabel: "> 0%",
      passWhen: (value) => parseOptionalNumber(value) !== null && parseOptionalNumber(value) > 0,
    }),
    buildPromotionItem({
      key: "profit_factor",
      label: "Profit factor",
      actual: metrics.out_of_sample_profit_factor,
      actualLabel: formatSigned(metrics.out_of_sample_profit_factor, 2),
      targetLabel: ">= 1.30",
      passWhen: (value) => parseOptionalNumber(value) !== null && parseOptionalNumber(value) >= 1.3,
    }),
    buildPromotionItem({
      key: "win_rate",
      label: "Win rate",
      actual: metrics.out_of_sample_win_rate,
      actualLabel: formatPercent(metrics.out_of_sample_win_rate, 0),
      targetLabel: ">= 45%",
      passWhen: (value) => parseOptionalNumber(value) !== null && parseOptionalNumber(value) >= 45,
    }),
    buildPromotionItem({
      key: "drawdown",
      label: "Drawdown",
      actual: metrics.out_of_sample_max_drawdown_percent,
      actualLabel: formatPercent(metrics.out_of_sample_max_drawdown_percent, 2),
      targetLabel: "<= 20%",
      passWhen: (value) => parseOptionalNumber(value) !== null && parseOptionalNumber(value) <= 20,
    }),
    buildPromotionItem({
      key: "payoff_ratio",
      label: "Payoff ratio",
      actual: metrics.out_of_sample_payoff_ratio,
      actualLabel: formatSigned(metrics.out_of_sample_payoff_ratio, 2),
      targetLabel: ">= 1.50",
      passWhen: (value) => parseOptionalNumber(value) !== null && parseOptionalNumber(value) >= 1.5,
    }),
    buildPromotionItem({
      key: "fold_consistency",
      label: "Fold consistency",
      actual: profitableFoldPercent,
      actualLabel: profitableFoldPercent === null ? "N/A" : formatPercent(profitableFoldPercent, 0),
      targetLabel: ">= 50% profitable folds",
      passWhen: (value) => parseOptionalNumber(value) !== null && parseOptionalNumber(value) >= 50,
      watchWhen: (value) => parseOptionalNumber(value) !== null && parseOptionalNumber(value) >= 40,
    }),
    buildPromotionItem({
      key: "architecture_gate",
      label: "Architecture gate",
      actual: gateStatus,
      actualLabel: gateStatus,
      targetLabel: "PASS",
      passWhen: (value) => value === "PASS",
      watchWhen: (value) => value === "INSUFFICIENT_EVIDENCE" || value === "PARTIAL",
      passPoints: 1,
      watchPoints: 0.5,
    }),
  ];

  const score = Number(items.reduce((sum, item) => sum + item.points, 0).toFixed(1));
  const maxScore = items.reduce((sum, item) => sum + item.maxPoints, 0);

  let decision = "BLOCKED";
  if (score >= 5 && contractStatus === "PASS" && foldCount >= minimumFolds && gateStatus !== "FAIL") {
    decision = "VALIDATION_WATCHLIST";
  }
  if (score >= 6.5 && contractStatus === "PASS" && foldCount >= minimumFolds && gateStatus === "PASS") {
    decision = "PROMOTION_CANDIDATE";
  }
  if (!promotionAllowed) {
    decision = "BLOCKED_R0";
  }

  return {
    decision,
    score,
    maxScore,
    scoreLabel: `${score.toFixed(1)} / ${maxScore.toFixed(1)} points`,
    items,
    summary: !promotionAllowed
      ? "R0 truth repair blocks promotion. Metrics remain diagnostic until canonical final candles and full point-in-time replay parity are regenerated."
      : buildPromotionSummary({ decision, score, contractStatus, foldCount, minimumFolds, gateStatus }),
  };
}

function buildPromotionItem({
  key,
  label,
  actual,
  actualLabel,
  targetLabel,
  passWhen,
  watchWhen,
  passPoints = 1,
  watchPoints = 0.5,
}) {
  const pass = passWhen?.(actual) === true;
  const watch = pass ? false : watchWhen?.(actual) === true;
  const status = pass ? "PASS" : watch ? "WATCH" : "FAIL";
  const points = pass ? passPoints : watch ? watchPoints : 0;
  return {
    key,
    label,
    actualLabel,
    targetLabel,
    status,
    points,
    maxPoints: passPoints,
    pointsLabel: `${points.toFixed(1)} / ${passPoints.toFixed(1)} points`,
  };
}

function buildPromotionSummary({ decision, score, contractStatus, foldCount, minimumFolds, gateStatus }) {
  if (decision === "PROMOTION_CANDIDATE") {
    return `This scope is behaving like a promotion candidate. Score ${score.toFixed(1)} with contract ${contractStatus}, folds ${foldCount}/${minimumFolds}, and architecture gate ${gateStatus}.`;
  }
  if (decision === "VALIDATION_WATCHLIST") {
    return `This scope is good enough to stay on the validation watchlist, but not yet strong enough for promotion. Contract ${contractStatus}, folds ${foldCount}/${minimumFolds}, architecture gate ${gateStatus}.`;
  }
  return `This scope stays blocked for promotion right now. Improve edge quality or evidence depth before considering graduation. Contract ${contractStatus}, folds ${foldCount}/${minimumFolds}, architecture gate ${gateStatus}.`;
}

function buildPhase3EntryGate(report, walkForwardResult, promotionScorecard) {
  if (!report || !promotionScorecard) return null;

  const metrics = report?.derived_metrics || {};
  const foldCount = safeNumber(report?.walk_forward?.fold_count, 0);
  const minimumFolds = safeNumber(report?.walk_forward?.contract?.minimum_fold_requirement, 0);
  const profitableFoldPercent = parseOptionalNumber(walkForwardResult?.robustness?.profitable_fold_percent);
  const gateStatus = String(report?.architecture_gate?.status || "UNKNOWN").toUpperCase();
  const overallStatus = String(report?.overall_status || "UNKNOWN").toUpperCase();
  const paperEvidenceAttached = !String(report?.next_action || "").toLowerCase().includes("paper");
  const promotionAllowed = report?.promotion_allowed !== false;

  const checks = [
    buildPhase3GateCheck({
      key: "r0_evidence_governance",
      label: "R0 evidence governance",
      actualLabel: report?.promotion_status || (promotionAllowed ? "Allowed" : "Blocked"),
      targetLabel: "Promotion allowed",
      pass: promotionAllowed,
      watch: false,
    }),
    buildPhase3GateCheck({
      key: "promotion_score",
      label: "Promotion score",
      actualLabel: promotionScorecard.scoreLabel,
      targetLabel: ">= 6.5 / 7.0",
      pass: promotionScorecard.score >= 6.5,
      watch: promotionScorecard.score >= 5,
    }),
    buildPhase3GateCheck({
      key: "overall_status",
      label: "Overall Phase 2 status",
      actualLabel: overallStatus,
      targetLabel: "PASS",
      pass: overallStatus === "PASS",
      watch: overallStatus === "PARTIAL",
    }),
    buildPhase3GateCheck({
      key: "architecture_gate",
      label: "Architecture gate",
      actualLabel: gateStatus,
      targetLabel: "PASS",
      pass: gateStatus === "PASS",
      watch: gateStatus === "INSUFFICIENT_EVIDENCE",
    }),
    buildPhase3GateCheck({
      key: "minimum_folds",
      label: "Minimum folds",
      actualLabel: `${foldCount}/${minimumFolds}`,
      targetLabel: `${minimumFolds}`,
      pass: minimumFolds > 0 && foldCount >= minimumFolds,
      watch: minimumFolds > 0 && foldCount >= Math.max(1, minimumFolds - 1),
    }),
    buildPhase3GateCheck({
      key: "profitable_folds",
      label: "Profitable folds",
      actualLabel: profitableFoldPercent === null ? "N/A" : formatPercent(profitableFoldPercent, 0),
      targetLabel: ">= 50%",
      pass: profitableFoldPercent !== null && profitableFoldPercent >= 50,
      watch: profitableFoldPercent !== null && profitableFoldPercent >= 40,
    }),
    buildPhase3GateCheck({
      key: "max_drawdown",
      label: "Max drawdown",
      actualLabel: formatPercent(metrics.out_of_sample_max_drawdown_percent, 2),
      targetLabel: "<= 20%",
      pass: parseOptionalNumber(metrics.out_of_sample_max_drawdown_percent) !== null && parseOptionalNumber(metrics.out_of_sample_max_drawdown_percent) <= 20,
      watch: parseOptionalNumber(metrics.out_of_sample_max_drawdown_percent) !== null && parseOptionalNumber(metrics.out_of_sample_max_drawdown_percent) <= 25,
    }),
    buildPhase3GateCheck({
      key: "paper_evidence",
      label: "Paper evidence attached",
      actualLabel: paperEvidenceAttached ? "Attached or implied" : "Missing",
      targetLabel: "Required",
      pass: paperEvidenceAttached,
      watch: false,
    }),
  ];

  const passedChecks = checks.filter((check) => check.status === "PASS").length;
  const blockers = checks.filter((check) => check.status === "FAIL").map((check) => check.label);

  let status = "NOT_READY";
  if (checks.every((check) => check.status === "PASS")) {
    status = "READY_FOR_PHASE3";
  } else if (passedChecks >= 4 && promotionScorecard.decision !== "BLOCKED") {
    status = "PHASE2_WATCHLIST";
  }

  return {
    status,
    checks,
    passedChecks,
    totalChecks: checks.length,
    blockers,
    summary: buildPhase3EntryGateSummary(status, passedChecks, checks.length, blockers),
  };
}

function buildPhase3GateCheck({ key, label, actualLabel, targetLabel, pass, watch }) {
  return {
    key,
    label,
    actualLabel,
    targetLabel,
    status: pass ? "PASS" : watch ? "WATCH" : "FAIL",
  };
}

function buildPhase3EntryGateSummary(status, passedChecks, totalChecks, blockers) {
  if (status === "READY_FOR_PHASE3") {
    return `This setup meets the explicit Phase 3 entry gate with ${passedChecks}/${totalChecks} checks passing. It is ready for controlled execution-readiness review.`;
  }
  if (status === "PHASE2_WATCHLIST") {
    return `This setup is close, but still belongs in the Phase 2 watchlist. ${passedChecks}/${totalChecks} checks pass; remaining blockers: ${blockers.join(", ") || "none listed"}.`;
  }
  return `This setup is not ready for Phase 3 yet. ${passedChecks}/${totalChecks} checks pass; blockers: ${blockers.join(", ") || "insufficient validation quality"}.`;
}

function compareOptionalNumberDesc(leftValue, rightValue, leftSavedAt, rightSavedAt) {
  const left = parseOptionalNumber(leftValue);
  const right = parseOptionalNumber(rightValue);
  if (left === null && right === null) return compareSavedAtDesc(leftSavedAt, rightSavedAt);
  if (left === null) return 1;
  if (right === null) return -1;
  return right - left || compareSavedAtDesc(leftSavedAt, rightSavedAt);
}

function compareOptionalNumberAsc(leftValue, rightValue, leftSavedAt, rightSavedAt) {
  const left = parseOptionalNumber(leftValue);
  const right = parseOptionalNumber(rightValue);
  if (left === null && right === null) return compareSavedAtDesc(leftSavedAt, rightSavedAt);
  if (left === null) return 1;
  if (right === null) return -1;
  return left - right || compareSavedAtDesc(leftSavedAt, rightSavedAt);
}

function compareSavedAtDesc(leftSavedAt, rightSavedAt) {
  return (Date.parse(rightSavedAt || "") || 0) - (Date.parse(leftSavedAt || "") || 0);
}

function timeframeSortOrder(left, right) {
  const order = ["5m", "15m", "1h", "4h", "1d"];
  const leftIndex = order.indexOf(left);
  const rightIndex = order.indexOf(right);
  if (leftIndex === -1 && rightIndex === -1) return String(left).localeCompare(String(right));
  if (leftIndex === -1) return 1;
  if (rightIndex === -1) return -1;
  return leftIndex - rightIndex;
}

function comparePhase2SummaryRecords(left, right, sortKey) {
  const leftSavedAt = Date.parse(left?.saved_at || "") || 0;
  const rightSavedAt = Date.parse(right?.saved_at || "") || 0;
  const leftReturn = parseOptionalNumber(left?.drift?.out_of_sample_total_return_percent) ?? Number.NEGATIVE_INFINITY;
  const rightReturn = parseOptionalNumber(right?.drift?.out_of_sample_total_return_percent) ?? Number.NEGATIVE_INFINITY;
  const leftPf = parseOptionalNumber(left?.drift?.out_of_sample_profit_factor) ?? Number.NEGATIVE_INFINITY;
  const rightPf = parseOptionalNumber(right?.drift?.out_of_sample_profit_factor) ?? Number.NEGATIVE_INFINITY;
  const leftDd = parseOptionalNumber(left?.drift?.out_of_sample_max_drawdown_percent) ?? Number.POSITIVE_INFINITY;
  const rightDd = parseOptionalNumber(right?.drift?.out_of_sample_max_drawdown_percent) ?? Number.POSITIVE_INFINITY;
  const leftSamples = safeNumber(left?.sample_count, 0);
  const rightSamples = safeNumber(right?.sample_count, 0);

  switch (sortKey) {
    case "BEST_RETURN":
      return rightReturn - leftReturn || rightSavedAt - leftSavedAt;
    case "WORST_RETURN":
      return leftReturn - rightReturn || rightSavedAt - leftSavedAt;
    case "BEST_PF":
      return rightPf - leftPf || rightSavedAt - leftSavedAt;
    case "WORST_DD":
      return rightDd - leftDd || rightSavedAt - leftSavedAt;
    case "MOST_SAMPLES":
      return rightSamples - leftSamples || rightSavedAt - leftSavedAt;
    case "LATEST":
    default:
      return rightSavedAt - leftSavedAt;
  }
}

function statusChangeTone(value) {
  if (!value || value === "UNCHANGED" || value === "FIRST_SAMPLE") return "slate";
  if (String(value).includes("_TO_PASS") || String(value).includes("FAIL_TO_") || String(value).includes("INSUFFICIENT_EVIDENCE_TO_PARTIAL")) {
    return "emerald";
  }
  return "amber";
}

function humanizeStatusChange(value) {
  if (!value) return "Unknown";
  if (value === "UNCHANGED") return "Unchanged";
  if (value === "FIRST_SAMPLE") return "First sample";
  return String(value)
    .replace(/_TO_/g, " → ")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function normalizeFamilyEntries(items) {
  if (!items || typeof items !== "object") return [];
  return Object.entries(items).filter(([, value]) => {
    if (Array.isArray(value)) return value.length > 0;
    return value !== null && value !== undefined && value !== 0;
  });
}

function formatFamilyValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "number") return String(value);
  return value || "-";
}

function humanizeKey(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function parityTone(label) {
  if (label === "PAPER_SIMILAR_TO_REPLAY") return "emerald";
  if (label === "PAPER_TIGHTER_THAN_REPLAY" || label === "PAPER_WIDER_THAN_REPLAY") return "amber";
  return "slate";
}

function eligibilityTone(coveragePercent) {
  const value = safeNumber(coveragePercent, 0);
  if (value >= 70) return "emerald";
  if (value >= 40) return "amber";
  return "rose";
}

function coverageTone(coverage) {
  const hitRate = coverageRate(coverage);
  if (hitRate >= 70) return "emerald";
  if (hitRate >= 40) return "amber";
  return "rose";
}

function coverageLabel(coverage) {
  if (!coverage?.evaluated_decisions) return "No coverage";
  return `${formatPercent(coverageRate(coverage), 0)} snapshot hit`;
}

function coverageRate(coverage) {
  const evaluated = safeNumber(coverage?.evaluated_decisions, 0);
  const hits = safeNumber(coverage?.feature_snapshot_hits, 0);
  if (!evaluated) return 0;
  return (hits / evaluated) * 100;
}

function topReplayBlockerEntry(rejections) {
  const entries = normalizeFamilyEntries(rejections);
  if (!entries.length) return null;
  return entries.sort(([, left], [, right]) => safeNumber(right, 0) - safeNumber(left, 0))[0];
}

function topReplayBlockerLabel(rejections) {
  const entry = topReplayBlockerEntry(rejections);
  if (!entry) return "None";
  return humanizeKey(entry[0]);
}

function topReplayBlockerCountNote(rejections) {
  const entry = topReplayBlockerEntry(rejections);
  if (!entry) return "No replay blockers recorded";
  return `${entry[1]} blocked decisions`;
}

function coverageDiagnosticNote(coverage) {
  if (!coverage?.evaluated_decisions) return "No replay decisions available";
  const hits = safeNumber(coverage?.feature_snapshot_hits, 0);
  const fallbacks = safeNumber(coverage?.feature_reconstructed_fallbacks, 0);
  return `${hits} snapshot hits, ${fallbacks} reconstructed fallbacks`;
}

function parityShortLabel(label) {
  if (label === "PAPER_SIMILAR_TO_REPLAY") return "Aligned";
  if (label === "PAPER_WIDER_THAN_REPLAY") return "Paper wider";
  if (label === "PAPER_TIGHTER_THAN_REPLAY") return "Paper tighter";
  return label || "Pending";
}

function sumTradesWithinDays(trades, days) {
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return Number(
    trades
      .filter((trade) => tradeDateValue(trade) >= cutoff)
      .reduce((sum, trade) => sum + tradePnlValue(trade), 0)
      .toFixed(2)
  );
}

function tradeDateValue(trade) {
  return new Date(trade.closed_at || trade.exit_time || trade.created_at || trade.entry_time || 0).getTime() || 0;
}

function tradePnlValue(trade) {
  if (trade?.pnl !== null && trade?.pnl !== undefined) return safeNumber(trade.pnl, 0);
  return safeNumber(trade?.pnl_percent, 0);
}

function formatSelectionCounts(items) {
  if (!items?.length) return "No parameter selections yet";
  return items
    .slice(0, 2)
    .map((item) => `${item.stop_percent}/${item.target_percent} (${item.folds})`)
    .join(", ");
}
