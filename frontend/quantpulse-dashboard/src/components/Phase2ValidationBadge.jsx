import { useEffect, useMemo, useState } from "react";
import Pill from "./ui/Pill";
import { loadWalkForwardSummary } from "../hooks/dashboardApi";

export default function Phase2ValidationBadge({ symbol, timeframe = "15m", signalType, className = "" }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const signalSide = useMemo(() => {
    if (signalType === "BUY") return "LONG";
    if (signalType === "SELL") return "SHORT";
    return null;
  }, [signalType]);

  const result = summary?.result || null;
  const contract = result?.validation_contract || null;

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      if (!symbol || !signalSide) {
        setSummary(null);
        setError("");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError("");

      try {
        const response = await loadWalkForwardSummary({
          symbol,
          signalSide,
          timeframe,
          signal: controller.signal,
        });

        if (!cancelled) {
          setSummary(response);
        }
      } catch (err) {
        if (!cancelled && err?.name !== "AbortError") {
          setSummary(null);
          setError(err instanceof Error ? err.message : "Unable to load Phase 2 validation status");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [symbol, timeframe, signalSide]);

  if (!signalSide) {
    return (
      <div className={`rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5 ${className}`}>
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Phase 2 validation</div>
            <div className="mt-1 text-xs text-slate-400">Waiting for BUY or SELL signal</div>
          </div>
          <Pill tone="slate">Idle</Pill>
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2.5 ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Phase 2 validation</div>
          <div className="mt-1 text-xs text-slate-400">
            {symbol} {signalSide} · {timeframe}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Pill tone={loading ? "amber" : contractTone(contract?.contract_status)}>{loading ? "Loading" : contract?.contract_status || "Pending"}</Pill>
          {contract?.timeframe_status ? <Pill tone={timeframeTone(contract.timeframe_status)}>{contract.timeframe_status}</Pill> : null}
        </div>
      </div>

      {error ? <div className="mt-2 text-xs text-rose-300">{error}</div> : null}

      {!error ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
          <span>Folds: {result?.fold_count ?? "-"}</span>
          <span>Min required: {contract?.minimum_fold_requirement ?? "-"}</span>
          <span>Config match: {contractLabel(contract?.configuration_matches_contract)}</span>
        </div>
      ) : null}

      {!error && contract?.issues?.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {contract.issues.slice(0, 2).map((issue) => (
            <Pill key={issue} tone={issueTone(issue)}>
              {humanizeIssue(issue)}
            </Pill>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function contractTone(status) {
  if (status === "PASS") return "emerald";
  if (status === "PARTIAL" || status === "INSUFFICIENT_EVIDENCE") return "amber";
  if (status === "FAIL") return "rose";
  return "slate";
}

function timeframeTone(status) {
  if (status === "OFFICIAL") return "emerald";
  if (status === "SUPPORTING") return "amber";
  return "slate";
}

function issueTone(issue) {
  if (issue === "walk_forward_windows_do_not_match_phase2_contract") return "rose";
  if (issue === "minimum_fold_requirement_not_met" || issue === "insufficient_history_for_phase2_fold_requirement") return "amber";
  return "slate";
}

function contractLabel(value) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "N/A";
}

function humanizeIssue(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}
