import { Filter, ShieldAlert } from "lucide-react";

const SECTION = "mx-auto w-full max-w-[1680px] px-4 sm:px-6 lg:px-8";

export default function DashboardFooter({ selectedPipeline, loading }) {
  return (
    <footer className={`${SECTION} flex flex-wrap items-center justify-between gap-3 py-3 text-xs text-slate-500`}>
      <div className="inline-flex items-center gap-2">
        <Filter className="h-4 w-4" />
        {selectedPipeline?.status || "PIPELINE_UNKNOWN"}
      </div>
      <div className="inline-flex items-center gap-2">
        <ShieldAlert className="h-4 w-4" />
        {loading ? "Refreshing" : "Live"}
      </div>
    </footer>
  );
}
