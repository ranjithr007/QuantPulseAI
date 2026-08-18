import clsx from "clsx";
import { formatPercent, formatPrice, formatSigned, formatTargets } from "../utils/formatters";
import { enrichRow } from "./MarketSignalTable";

const SIGNAL_SIDES = ["ALL", "LONG", "SHORT"];
const EXECUTOR_STATUS_OPTIONS = ["ALL", "READY", "BLOCKED", "NO_QUEUED_PLAN"];

export default function SignalScannerSection({ view, filters, setView, setFilters, signalRows, watchlist, liveStatus, auto, paperTradeCandidates, onOpenSignal }) {
  function selectSignal(symbol) {
    setView((current) => ({ ...current, symbol }));
    onOpenSignal?.(symbol);
  }

  const enrichedRows = signalRows.map((row) =>
    enrichRow(row, watchlist, liveStatus, auto?.minConfidence ?? 40, paperTradeCandidates)
  );
  const actionableRows = enrichedRows.filter((row) => row.type === "BUY" || row.type === "SELL");
  const sideFilteredRows = actionableRows.filter((row) => matchesSideFilter(row, filters.watchlistSide));
  const filteredRows = sideFilteredRows.filter((row) => matchesExecutorFilter(row, filters.executorStatus));
  const longCount = actionableRows.filter((row) => row.type === "BUY").length;
  const shortCount = actionableRows.filter((row) => row.type === "SELL").length;
  const executorReadyCount = actionableRows.filter((row) => row.executorStatus === "READY").length;
  const blockedCount = actionableRows.filter((row) => ["BLOCKED", "STALE"].includes(row.executorStatus)).length;

  return (
    <section className="border-b border-white/5">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-5 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-2.5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-slate-500">Signal Scanner</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-white sm:text-xl">Actionable signals</h2>
            <p className="mt-1 text-sm text-slate-500">Current BUY/SELL setups only. Neutral and WAIT coins remain in the Market overview.</p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <ScannerSelect
              label="Signal side"
              value={filters.watchlistSide}
              options={SIGNAL_SIDES}
              onChange={(value) => setFilters((current) => ({ ...current, watchlistSide: value }))}
            />
            <ScannerSelect
              label="Executor"
              value={filters.executorStatus}
              options={EXECUTOR_STATUS_OPTIONS}
              onChange={(value) => setFilters((current) => ({ ...current, executorStatus: value }))}
            />
          </div>
        </div>

        <div className="mt-3.5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <SignalSummary label="Actionable" value={actionableRows.length} note="BUY + SELL" tone="cyan" />
          <SignalSummary label="Long" value={longCount} note="Current BUY setups" tone="emerald" />
          <SignalSummary label="Short" value={shortCount} note="Current SELL setups" tone="rose" />
          <SignalSummary label="Executor" value={executorReadyCount} note={`${blockedCount} blocked`} tone={executorReadyCount ? "emerald" : "amber"} />
        </div>

        <div className="mt-3.5 grid gap-3 xl:grid-cols-3">
          {filteredRows.map((row) => (
            <SignalCard
              key={row.symbol}
              row={row}
              active={view.symbol === row.symbol}
              onClick={() => selectSignal(row.symbol)}
            />
          ))}
          {!filteredRows.length ? (
            <div className="rounded-lg border border-dashed border-white/10 bg-slate-900/50 p-6 text-center xl:col-span-3">
              <div className="text-sm font-medium text-slate-200">No actionable signal matches the current filters</div>
              <div className="mt-1 text-xs text-slate-500">The system continues scanning 1h, 2h, 4h and 1d. WAIT coins are available on the Market page.</div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ScannerSelect({ label, value, options, onChange }) {
  return (
    <label className="grid gap-2">
      <span className="text-[10px] uppercase tracking-[0.2em] text-slate-500">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-white outline-none transition hover:border-white/20 focus:border-cyan-400/40"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function SignalCard({ row, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "group rounded-lg border p-3 text-left transition duration-200",
        active
          ? "border-cyan-400/45 bg-cyan-500/10 shadow-lg shadow-cyan-950/25"
          : "border-white/10 bg-slate-900/70 hover:border-white/20 hover:bg-slate-900"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-base font-semibold text-white sm:text-lg">{row.symbol}</div>
          <div className="mt-1 text-[10px] uppercase tracking-[0.2em] text-slate-500">{row.regime}</div>
        </div>
        <SignalBadge type={row.type} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <MiniLine label="Confidence" value={formatPercent(row.confidence)} />
        <MiniLine label="RR" value={formatSigned(row.riskReward, 2)} />
        <MiniLine label="Current price" value={formatPrice(row.currentPrice)} />
        <MiniLine label="Planned entry" value={formatPrice(row.entry)} />
        <MiniLine label="Stop" value={formatPrice(row.stopLoss)} />
        <MiniLine label="Spot confirmation" value={`${row.participationDirection || "UNAVAILABLE"} · ${formatPercent(row.participationConfidence, 0, "-")}`} />
      </div>

      <div className="mt-3 space-y-1.5">
        <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Targets</div>
        <div className="text-sm text-slate-300">{formatTargets(row.targets)}</div>
        <div className="line-clamp-2 text-xs leading-5 text-slate-400">{row.reason}</div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <StatusLine label="Eligibility" value={row.riskLabel} tone={row.riskTone} note={row.riskNote} />
        <StatusLine label="Executor" value={row.executorLabel} tone={row.executorTone} note={row.executorNote} />
      </div>
    </button>
  );
}

function SignalSummary({ label, value, note, tone }) {
  const toneClass = tone === "emerald" ? "text-emerald-300" : tone === "rose" ? "text-rose-300" : tone === "amber" ? "text-amber-300" : "text-cyan-300";
  return <div className="rounded-lg border border-white/10 bg-slate-900/70 p-3"><div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div><div className={`mt-1 text-xl font-semibold ${toneClass}`}>{value}</div><div className="mt-1 text-xs text-slate-500">{note}</div></div>;
}

function StatusLine({ label, value, tone, note }) {
  const toneClass = tone === "emerald" ? "text-emerald-300" : tone === "rose" ? "text-rose-300" : tone === "amber" ? "text-amber-300" : "text-slate-300";
  return <div className="rounded-md border border-white/5 bg-slate-950/70 p-2.5"><div className="text-[9px] uppercase tracking-[0.14em] text-slate-500">{label}</div><div className={`mt-1 text-xs font-medium ${toneClass}`}>{value || "Unknown"}</div><div className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-500">{note || "No additional context"}</div></div>;
}

function SignalBadge({ type }) {
  const toneClass =
    type === "BUY"
      ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-200"
      : type === "SELL"
        ? "border-rose-400/25 bg-rose-500/10 text-rose-200"
        : "border-white/10 bg-slate-950/70 text-slate-200";

  return <span className={clsx("inline-flex items-center rounded-full px-3 py-1 text-xs font-medium", toneClass)}>{type}</span>;
}

function MiniLine({ label, value }) {
  return (
    <div className="rounded-lg border border-white/5 bg-slate-950/70 p-2.5">
      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-white">{value}</div>
    </div>
  );
}

function matchesExecutorFilter(row, filter) {
  const value = String(filter || "ALL").toUpperCase();
  if (value === "ALL") return true;
  if (value === "READY") return row.executorStatus === "READY";
  if (value === "BLOCKED") return row.executorStatus === "BLOCKED" || row.executorStatus === "STALE";
  if (value === "NO_QUEUED_PLAN") return row.executorStatus === "NO_QUEUED_PLAN";
  return true;
}

function matchesSideFilter(row, filter) {
  const value = String(filter || "ALL").toUpperCase();
  if (value === "ALL") return true;
  if (value === "LONG") return row.type === "BUY";
  if (value === "SHORT") return row.type === "SELL";
  return true;
}
