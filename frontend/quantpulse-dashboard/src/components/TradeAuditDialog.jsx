import { useEffect, useRef } from "react";
import ExitPolicyEvidence from "./ExitPolicyEvidence";
import { formatDate, formatInr, formatPrice } from "../utils/formatters";
import { EXIT_CLASSIFICATIONS, recordedNumber, tradeExitClassification } from "../utils/tradeAudit";

const missing = "Not recorded";
const percentage = (value) => recordedNumber(value) == null ? missing : `${Number(value).toFixed(3)}%`;
const price = (value) => recordedNumber(value) == null ? missing : formatPrice(value);
const money = (value) => recordedNumber(value) == null ? missing : formatInr(value);
const date = (value) => value ? formatDate(value) : missing;

export default function TradeAuditDialog({ trade, onClose, ledgerLabel = "Consolidated paper ledger" }) {
  const dialogRef = useRef(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  const entry = trade.execution_evidence || {};
  const exit = trade.exit_evidence || {};
  const observation = exit.observations || {};
  const sizing = trade.paper_sizing || {};
  const riskSizing = entry.risk_sizing || {};
  return (
    <dialog ref={dialogRef} onCancel={onClose} aria-labelledby="trade-audit-title"
      className="fixed inset-0 m-auto max-h-[85vh] w-[min(760px,95vw)] overflow-y-auto rounded-xl border border-white/10 bg-slate-900 p-5 text-slate-200 shadow-xl backdrop:bg-slate-950/50">
      <div className="flex items-center justify-between gap-3">
        <h3 id="trade-audit-title" className="text-base font-semibold text-white">{trade.symbol} trade {trade.id} audit</h3>
        <button type="button" onClick={onClose} autoFocus className="rounded-md border border-white/10 px-3 py-2 text-sm">Close audit</button>
      </div>
      <p className="mt-2 text-xs text-slate-400">{ledgerLabel} · {trade.side} · {trade.entry_timeframe || "Timeframe not recorded"}. Recorded evidence only; no exit subtype is inferred from profit or loss.</p>
      <AuditGroup title="Identity and policy">
        <AuditDatum label="Strategy / version" value={`${trade.strategy_id || missing} / ${trade.strategy_version || missing}`} />
        <AuditDatum label="Exit classification" value={EXIT_CLASSIFICATIONS[tradeExitClassification(trade)]} />
        <AuditDatum label="Opened (IST)" value={date(trade.opened_at || trade.created_at)} />
        <AuditDatum label="Closed (IST)" value={date(trade.closed_at)} />
        <AuditDatum label="Trailing activation" value={recordedNumber(trade.trailing_activation_r) == null ? missing : `${trade.trailing_activation_r}R`} />
        <ExitPolicyEvidence trade={trade} />
      </AuditGroup>
      <AuditGroup title="Entry execution evidence">
        {!Object.keys(entry).length ? <p className="col-span-full text-xs text-amber-300">Entry execution evidence unavailable for this historical trade.</p> : null}
        <AuditDatum label="Planned entry" value={price(entry.signal_planned_entry_price ?? trade.planned_entry_price)} />
        <AuditDatum label="Actual entry fill" value={price(entry.entry_fill_price ?? trade.entry_price)} />
        <AuditDatum label="Observed execution price" value={price(entry.execution_mark_price)} />
        <AuditDatum label="Entry drift" value={percentage(entry.entry_drift_percent)} />
        <AuditDatum label="Observed at (IST)" value={date(entry.execution_mark_observed_at)} />
        <AuditDatum label="Price source" value={entry.execution_mark_source || missing} />
        <AuditDatum label="Entry / exit profile" value={`${entry.entry_quality_profile || missing} / ${entry.exit_management_profile || missing}`} />
        <AuditDatum label="Release evidence version" value={entry.release_version || missing} />
        <AuditDatum label="Sizing policy" value={sizing.sizing_policy || entry.sizing_policy || missing} />
        <AuditDatum label="Equity at entry" value={money(riskSizing.equity_at_entry_inr)} />
        <AuditDatum label="Intended risk budget" value={`${money(riskSizing.risk_budget_inr)} / ${percentage(riskSizing.risk_budget_percent)}`} />
        <AuditDatum label="Estimated loss at stop" value={money(riskSizing.estimated_max_loss_inr)} />
        <p className="col-span-full text-xs text-slate-500">Risk sizing is an estimate, not a guaranteed maximum loss; gaps, slippage and funding can differ from the modeled reserve.</p>
      </AuditGroup>
      <AuditGroup title="Exit execution evidence">
        {!Object.keys(exit).length ? <p className="col-span-full text-xs text-amber-300">Exit trigger evidence unavailable for this historical trade. This loss cannot be assigned to entry quality or trailing from the summary alone.</p> : null}
        <AuditDatum label="Trigger type" value={exit.trigger_type || missing} />
        <AuditDatum label="Initial stop" value={price(exit.initial_stop_loss ?? trade.recorded_initial_stop_loss)} />
        <AuditDatum label="Active stop at trigger" value={price(exit.active_stop_before_trigger)} />
        <AuditDatum label="Trigger price" value={price(exit.trigger_price)} />
        <AuditDatum label="Exit fill" value={price(exit.exit_fill_price ?? trade.exit_price)} />
        <AuditDatum label="Observed price" value={price(exit.observed_price)} />
        <AuditDatum label="Observed at (IST)" value={date(exit.observed_at)} />
        <AuditDatum label="Processed at (IST)" value={date(exit.processed_at)} />
        <AuditDatum label="Evidence age at processing" value={recordedNumber(exit.quote_age_seconds) == null ? missing : `${exit.quote_age_seconds}s`} />
        <AuditDatum label="Source / evidence kind" value={`${exit.source || missing} / ${exit.evidence_kind || missing}`} />
        <AuditDatum label="Observed favorable excursion" value={percentage(observation.mfe_percent)} />
        <AuditDatum label="Observed adverse excursion" value={percentage(observation.mae_percent)} />
        <p className="col-span-full text-xs text-slate-500">Excursions reflect recorded observations only, not a complete tick-by-tick price path. Evidence age for candle reconciliation is not measured worker latency. Missing values are not zero.</p>
      </AuditGroup>
      <AuditGroup title="Recorded costs and result">
        <AuditDatum label="Gross trade return" value={percentage(trade.gross_pnl_percent)} />
        <AuditDatum label="Fees" value={percentage(trade.fees_percent)} />
        <AuditDatum label="Funding" value={percentage(trade.funding_cost_percent)} />
        <AuditDatum label="Exit slippage" value={percentage(trade.exit_slippage_percent)} />
        <AuditDatum label="Net trade return" value={percentage(trade.pnl_percent)} />
        <AuditDatum label="Net paper P&L" value={money(sizing.realized_pnl_inr ?? trade.realized_pnl_inr)} />
        <p className="col-span-full text-xs text-slate-500">Trade percentages are not account returns. Slippage may already be reflected in fill prices; do not subtract it again.</p>
      </AuditGroup>
    </dialog>
  );
}

function AuditGroup({ title, children }) {
  return <section className="mt-4 border-t border-white/10 pt-3"><h4 className="mb-2 text-sm font-medium text-white">{title}</h4><dl className="grid gap-3 sm:grid-cols-2">{children}</dl></section>;
}
function AuditDatum({ label, value }) {
  return <div className="min-w-0"><dt className="text-[11px] text-slate-500">{label}</dt><dd className="mt-0.5 break-words text-xs">{value}</dd></div>;
}
