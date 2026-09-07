import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { loadPaperTrades } from "../hooks/dashboardApi";
import { cacheHistoryPage, cachedHistoryPage, PAPER_HISTORY_PAGE_SIZE, paginationPageNumbers, validatedHistoryPage, visibleHistoryPage } from "../utils/paperHistory";
import { EXIT_CLASSIFICATIONS, tradeExitBreakdown, tradeExitClassification } from "../utils/tradeAudit";
import { formatDate, formatSigned, formatPrice, safeNumber } from "../utils/formatters";
import Pill from "./ui/Pill";
import TradeAuditDialog from "./TradeAuditDialog";

export default function PaperTradeHistory({ tradeHistory = [], totalCount }) {
  const [currentPage, setCurrentPage] = useState(1);
  const [snapshot, setSnapshot] = useState(null);
  const [remoteTotal, setRemoteTotal] = useState(totalCount ?? tradeHistory.length);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [auditTrade, setAuditTrade] = useState(null);
  const cache = useRef(new Map());
  const revision = `${tradeHistory[0]?.id ?? "none"}:${totalCount ?? tradeHistory.length}`;
  const totalItems = Math.max(0, remoteTotal ?? totalCount ?? tradeHistory.length);
  const totalPages = Math.max(1, Math.ceil(totalItems / PAPER_HISTORY_PAGE_SIZE));
  const verifiedPage = visibleHistoryPage(snapshot, currentPage, revision, error);
  const visibleTrades = verifiedPage?.records || [];
  const pageStart = (currentPage - 1) * PAPER_HISTORY_PAGE_SIZE;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setError("");
    setAuditTrade(null);
    const cached = cachedHistoryPage(cache.current, currentPage, revision);
    if (cached) {
      setSnapshot(cached);
      setRemoteTotal(cached.total);
      setLoading(false);
      return () => { active = false; controller.abort(); };
    }
    setSnapshot(null);
    setLoading(true);
    loadPaperTrades({ status: "CLOSED", page: currentPage, limit: PAPER_HISTORY_PAGE_SIZE, signal: controller.signal })
      .then((response) => {
        if (!active) return;
        const page = validatedHistoryPage(response, currentPage, revision);
        cacheHistoryPage(cache.current, page);
        setRemoteTotal(page.total);
        if (currentPage > Math.max(1, Math.ceil(page.total / PAPER_HISTORY_PAGE_SIZE))) {
          setCurrentPage(Math.max(1, Math.ceil(page.total / PAPER_HISTORY_PAGE_SIZE)));
          return;
        }
        setSnapshot(page);
      })
      .catch((requestError) => {
        if (!active || requestError?.name === "AbortError") return;
        setSnapshot(null);
        cache.current.delete(currentPage);
        setError(requestError?.message || "Trade history is temporarily unavailable.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [currentPage, revision, retry]);

  const refresh = () => { cache.current.delete(currentPage); setRetry((value) => value + 1); };
  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-white/10 bg-slate-900/70 p-3" aria-busy={loading}>
      <div className="flex items-center justify-between gap-3">
        <div><div className="text-sm font-medium text-white">Trade history</div><div className="text-xs text-slate-500">Consolidated closed paper trades · audit details per trade</div></div>
        <div className="flex items-center gap-2"><Pill tone="slate">{totalItems} closed</Pill><button type="button" disabled={loading} onClick={refresh} className="rounded-md border border-white/10 px-2.5 py-1.5 text-xs disabled:opacity-40">{error ? "Retry page" : "Refresh page"}</button></div>
      </div>
      {error ? <div role="alert" className="mt-2 rounded-md border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">Page {currentPage} could not be loaded. {error} No earlier page rows are shown. Retry requests only this page.</div> : null}
      {visibleTrades.length ? <div className="mt-3 rounded-lg border border-white/10 p-2"><div className="mb-1 text-xs text-slate-500">Exit reasons · this {visibleTrades.length}-trade page only, not the full day or strategy cohort</div><div className="flex flex-wrap gap-2">{tradeExitBreakdown(visibleTrades).map(({ key, label, count }) => <Pill key={key} tone={key === "UNKNOWN" ? "amber" : "slate"}>{label}: {count}</Pill>)}</div></div> : null}
      <div className="mt-2.5 overflow-x-auto">
        <table className="min-w-full divide-y divide-white/5 text-sm">
          <thead className="bg-slate-950/60 text-[11px] uppercase tracking-[0.16em] text-slate-500"><tr>{["Symbol", "Side", "Entry", "Exit", "Net trade %", "Exit reason", "Closed (IST)", "Evidence"].map((label) => <th key={label} className="px-3 py-2.5 text-left">{label}</th>)}</tr></thead>
          <tbody className="divide-y divide-white/5">
            {visibleTrades.map((trade) => <tr key={trade.id} className="bg-slate-950/35">
              <td className="px-3 py-2.5 text-white">{trade.symbol}</td>
              <td className="px-3 py-2.5"><Pill tone={trade.side === "LONG" ? "emerald" : "rose"}>{trade.side}</Pill></td>
              <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.entry_price)}</td>
              <td className="px-3 py-2.5 text-slate-300">{formatPrice(trade.exit_price)}</td>
              <td className={clsx("px-3 py-2.5 font-medium", safeNumber(trade.pnl_percent, 0) >= 0 ? "text-emerald-300" : "text-rose-300")}>{formatSigned(trade.pnl_percent)}</td>
              <td className="px-3 py-2.5 text-slate-300">{EXIT_CLASSIFICATIONS[tradeExitClassification(trade)]}<div className="text-[10px] text-slate-500">{trade.result || "Result not recorded"}</div></td>
              <td className="px-3 py-2.5 text-slate-400">{trade.closed_at ? formatDate(trade.closed_at) : "Not recorded"}</td>
              <td className="px-3 py-2.5"><button type="button" className="rounded-md border border-white/10 px-2.5 py-1.5 text-xs" aria-label={`View audit ${trade.symbol} trade ${trade.id}`} onClick={() => setAuditTrade(trade)}>View audit</button></td>
            </tr>)}
            {!visibleTrades.length ? <tr><td className="px-3 py-3.5 text-slate-400" colSpan={8} role="status">{loading ? `Loading page ${currentPage}…` : error ? "No verified page loaded." : "No closed trades available."}</td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-col gap-2 border-t border-white/5 pt-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs text-slate-500" aria-live="polite">{verifiedPage ? `Showing ${visibleTrades.length ? pageStart + 1 : 0}–${pageStart + visibleTrades.length} of ${verifiedPage.total} closed trades · page ${currentPage}` : `Page ${currentPage} ${loading ? "loading" : "unavailable"}`}</div>
        <nav className="flex flex-wrap items-center gap-1" aria-label="Trade history pagination">
          <PaginationButton disabled={currentPage === 1} label="Previous" onClick={() => setCurrentPage((page) => Math.max(1, page - 1))} />
          {paginationPageNumbers(currentPage, totalPages).map((page) => <PaginationButton key={page} active={page === currentPage} label={String(page)} onClick={() => setCurrentPage(page)} />)}
          <PaginationButton disabled={currentPage >= totalPages} label="Next" onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))} />
        </nav>
      </div>
      {auditTrade ? <TradeAuditDialog trade={auditTrade} onClose={() => setAuditTrade(null)} /> : null}
    </div>
  );
}

function PaginationButton({ active = false, disabled = false, label, onClick }) {
  return <button type="button" className={clsx("min-w-8 rounded-md border px-2.5 py-1.5 text-xs font-medium transition", active ? "border-cyan-400/40 bg-cyan-500/15 text-cyan-200" : "border-white/10 bg-slate-950/40 text-slate-300", disabled && "cursor-not-allowed opacity-40")} disabled={disabled} aria-current={active ? "page" : undefined} onClick={onClick}>{label}</button>;
}
