import { useEffect, useState } from "react";
import { loadStrategyComparison } from "../hooks/dashboardApi";

const money = (value) => value == null ? "—" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);
const date = (value) => new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });

export default function StrategyBacktestComparison({ symbol }) {
  const [days, setDays] = useState(7);
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    let timer;
    setJob(null); setError(""); setSelected(""); setPage(0);
    async function refresh(jobId) {
      try {
        const result = await loadStrategyComparison({ symbol, days, jobId, signal: controller.signal });
        if (controller.signal.aborted) return;
        setJob(result);
        setError("");
        if (result.status === "COMPLETED") setPage(0);
        if (result.status === "FAILED") {
          setError(result.error || "The replay failed. Try a shorter period.");
          return;
        }
        timer = setTimeout(() => refresh(result.status === "COMPLETED" ? undefined : result.job_id), result.status === "COMPLETED" ? 3600000 : 5000);
      } catch (failure) {
        if (controller.signal.aborted) return;
        setError(failure.message);
      }
    }
    refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [symbol, days]);
  const report = job?.response;
  const results = report?.results || [];
  const key = (item) => `${item.strategy_id}:${item.version}`;
  const detail = results.find((item) => key(item) === selected) || results[0];
  const trades = [...(detail?.trades || [])].reverse();
  const pages = Math.max(1, Math.ceil(trades.length / 10));
  return <section className="my-5 rounded-xl border border-slate-300 bg-white p-4 text-slate-800" aria-label="All strategies backtest">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="text-lg font-semibold">All strategies · {symbol}</h3><p className="text-sm text-slate-600">Recorded decision replay · each strategy/version tested independently across 1h, 2h, 4h and 1d.</p></div>
      <label className="text-sm">Period <select aria-label="Strategy replay period" className="rounded border border-slate-300 bg-white p-2" value={days} onChange={(event) => { setJob(null); setDays(Number(event.target.value)); }}>
        {[1, 7, 14, 30].map((value) => <option key={value} value={value}>Last {value} day{value > 1 ? "s" : ""}</option>)}
      </select></label>
    </div>
    <p className="mt-2 text-xs text-slate-600">Runs automatically on selection; cached for one hour. No paper orders or strategy changes are made.</p>
    {error && <p role="alert" className="mt-3 text-red-700">{error}</p>}
    {!report && !error && <p role="status" className="mt-3">{job?.status || "Requesting"} — background strategy comparison…</p>}
    {report && <>
      <p className="my-3 text-sm">{date(report.start)} – {date(report.end)} IST · {report.price_bars} verified 5m bars ({report.price_coverage_percent}% price coverage) · {report.venue || "No price venue"}<br />{money(report.initial_capital_inr)} per version · {report.notional_percent}% notional · {report.fee_bps_per_side} bps fee per side</p>
      {report.last_price_at && <p className="mb-2 text-xs text-slate-600">Last stored price candle: {date(report.last_price_at)} IST</p>}
      <div className="overflow-x-auto"><table className="w-full text-left text-sm">
        <thead><tr>{["Strategy / version", "Coverage", "Decisions / eligible", "Closed / open", "Win rate", "PNL before funding", "T1 / T2 / stop", "Profit factor", "Realized DD"].map((label) => <th key={label} className="border-b p-2">{label}</th>)}</tr></thead>
        <tbody>{results.map((item) => {
          const hasHistory = item.status === "REPLAYED" || item.status === "INCOMPLETE";
          return <tr key={key(item)} className="border-b border-slate-100">
            <td className="p-2"><button className="text-left font-medium text-blue-700 underline" onClick={() => { setSelected(key(item)); setPage(0); }}>{item.name}</button><div className="text-xs text-slate-500">{item.version}</div></td>
            <td className="p-2">{item.status.replaceAll("_", " ")}{item.closed_trades < 30 && hasHistory && <div className="text-xs text-amber-700">Fewer than 30 closed trades</div>}</td>
            <td className="p-2">{item.decisions} / {item.eligible_decisions}</td>
            <td className="p-2">{hasHistory ? `${item.closed_trades} / ${item.open_positions}` : "—"}</td>
            <td className="p-2">{item.win_rate == null ? "—" : `${item.win_rate}%`}</td>
            <td className="p-2">{hasHistory ? money(item.pnl_inr) : "—"}</td>
            <td className="p-2">{hasHistory ? `${item.target1_hits} / ${item.target2_exits} / ${item.stop_exits}` : "—"}</td>
            <td className="p-2">{item.profit_factor ?? "—"}</td><td className="p-2">{hasHistory ? `${item.realized_drawdown_percent}%` : "—"}</td>
          </tr>;
        })}</tbody>
      </table></div>
      {detail && <div className="mt-4">
        <h4 className="font-semibold">{detail.name} · replay trade details</h4>
        <p className="text-xs text-slate-600">{detail.version} · select a strategy name above to change this summary. These are recorded-decision replay results, not walk-forward validation or paper PNL.</p>
        <div className="my-3 grid gap-3 sm:grid-cols-3">
          {[
            ["Period PNL before funding", ["REPLAYED", "INCOMPLETE"].includes(detail.status) ? money(detail.pnl_inr) : "Not available"],
            ["Closed trades", ["REPLAYED", "INCOMPLETE"].includes(detail.status) ? detail.closed_trades : "Not available"],
            ["Win rate", detail.win_rate == null ? "Not available" : `${detail.win_rate}%`],
            ["Realized drawdown", ["REPLAYED", "INCOMPLETE"].includes(detail.status) ? `${detail.realized_drawdown_percent}%` : "Not available"],
            ["Profit factor", detail.profit_factor ?? "Not available"],
            ["Average closed trade PNL", detail.closed_trades > 0 ? money(detail.pnl_inr / detail.closed_trades) : "Not available"],
          ].map(([label, value]) => <div key={label} className="rounded border border-slate-200 p-3"><div className="text-xs text-slate-500">{label}</div><div className="text-lg font-semibold">{value}</div></div>)}
        </div>
        <p className="text-xs text-slate-600">Latest {trades.length} of {detail.closed_trades} closed trades. T1 hits may also end at a stop; these counts overlap. Censored positions: {detail.censored_positions}.</p>
        {detail.excluded_decisions > 0 && <p className="text-xs text-amber-700">{detail.excluded_decisions} decisions excluded: missing completed pipeline lineage or invalid historical payload.</p>}
        {Object.entries(detail.skipped || {}).map(([reason, count]) => <p className="text-xs text-amber-700" key={reason}>{reason.replaceAll("_", " ")}: {count} candidate checks</p>)}
        {!trades.length ? <p className="py-2 text-sm">No closed replay trades in this window.</p> : <>
          <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>{["Entry (IST)", "Exit (IST)", "Side / TF", "Entry price", "Exit price", "Exit reason", "PNL before funding"].map((label) => <th className="p-2" key={label}>{label}</th>)}</tr></thead><tbody>
            {trades.slice(page * 10, page * 10 + 10).map((trade, index) => <tr key={`${trade.opened_at}:${index}`} className="border-t border-slate-100"><td className="p-2">{date(trade.opened_at)}</td><td className="p-2">{date(trade.closed_at)}</td><td className="p-2">{trade.side} / {trade.timeframe}</td><td className="p-2">{trade.entry}</td><td className="p-2">{trade.exit}</td><td className="p-2">{trade.reason}</td><td className="p-2">{money(trade.pnl_inr)}</td></tr>)}
          </tbody></table></div>
          <div className="mt-2 flex gap-3 text-sm"><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page + 1} of {pages}</span><button disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button></div>
        </>}
      </div>}
      <details className="mt-4 text-sm" open><summary className="cursor-pointer font-medium">Replay assumptions and limitations</summary><ul className="ml-5 mt-2 list-disc space-y-1">{report.limitations.map((text) => <li key={text}>{text}</li>)}</ul></details>
    </>}
  </section>;
}
