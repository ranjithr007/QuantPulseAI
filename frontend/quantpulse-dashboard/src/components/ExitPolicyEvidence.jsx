import { exitPolicyEvidence } from "../utils/exitPolicyEvidence";

export default function ExitPolicyEvidence({ trade }) {
  const evidence = exitPolicyEvidence(trade);
  return <div className="mt-1 max-w-[230px] text-[10px] text-slate-500">
    <div className="break-words">Recorded policy: {evidence.policy}</div>
    <div>Initial stop: {evidence.initialStop ?? "Not recorded"}{evidence.distancePercent == null ? "" : ` (${evidence.distancePercent.toFixed(3)}% from entry)`}</div>
  </div>;
}
