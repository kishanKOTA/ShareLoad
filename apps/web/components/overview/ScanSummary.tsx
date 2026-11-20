import type { AgentScanResult } from "@/lib/types";

export default function ScanSummary({ result }: { result: AgentScanResult }) {
  const isGemini = result.mode === "gemini";
  return (
    <section className="rounded-lg border border-sky-200 bg-sky-50 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-sky-900">
          Agent summary
        </h2>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            isGemini
              ? "bg-violet-100 text-violet-800 ring-1 ring-violet-200"
              : "bg-slate-200 text-slate-700 ring-1 ring-slate-300"
          }`}
          title={
            isGemini
              ? `Explained by ${result.model ?? "Gemini"}`
              : (result.fallback_reason ?? "Gemini unavailable; fixed template used")
          }
        >
          {isGemini ? `Gemini${result.model ? ` · ${result.model}` : ""}` : "Template"}
        </span>
        {result.cached && (
          <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200">
            Cached result
          </span>
        )}
        <span className="ml-auto text-xs text-sky-900/70">
          {result.candidates_considered} candidates · {result.opportunities.length} feasible ·{" "}
          {result.rejected.length} rejected
        </span>
      </div>
      <p className="mt-2 text-[15px] leading-relaxed text-slate-900">{result.agent_summary}</p>
      {!isGemini && result.fallback_reason && (
        <p className="mt-2 text-xs text-slate-600">Template mode: {result.fallback_reason}</p>
      )}
    </section>
  );
}
