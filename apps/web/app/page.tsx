"use client";

import { useState } from "react";
import OpportunityCard from "@/components/overview/OpportunityCard";
import RejectedCard from "@/components/overview/RejectedCard";
import ScanSummary from "@/components/overview/ScanSummary";
import ToolCallTimeline from "@/components/overview/ToolCallTimeline";
import { api, API_URL } from "@/lib/api";
import { useOrg } from "@/lib/org-context";
import type { AgentScanResult } from "@/lib/types";

export default function OverviewPage() {
  const { orgId, currentOrg } = useOrg();
  const [useCached, setUseCached] = useState(true);
  const [result, setResult] = useState<AgentScanResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runScan() {
    setRunning(true);
    setError(null);
    try {
      setResult(await api.scan(orgId, useCached));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Overview</h1>
          <p className="mt-1 text-sm text-slate-600">
            {currentOrg
              ? `Viewing as ${currentOrg.name} · ${currentOrg.region}`
              : "Find spare truck capacity that another business can use."}
          </p>
        </div>

        <div className="flex items-center gap-4">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={useCached}
              onChange={(e) => setUseCached(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 accent-slate-900"
            />
            Use cached result
          </label>
          <button
            onClick={runScan}
            disabled={running}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-wait disabled:opacity-60"
          >
            {running ? "Scanning…" : "Run scan"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Scan failed ({API_URL}): {error}
        </div>
      )}

      {!result && !error && !running && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Run a scan to have the agent look for trips with spare room that match another
          company&apos;s shipments.
        </div>
      )}

      {result && (
        <div className={`space-y-6 ${running ? "opacity-60" : ""}`} aria-busy={running}>
          <ScanSummary result={result} />
          <ToolCallTimeline calls={result.tool_calls} />

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Feasible opportunities ({result.opportunities.length})
            </h2>
            {result.opportunities.length ? (
              <div className="space-y-4">
                {result.opportunities.map((o) => (
                  <OpportunityCard key={o.id} opp={o} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No feasible matches in this scan.</p>
            )}
          </section>

          {result.rejected.length > 0 && (
            <section>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Rejected candidates ({result.rejected.length})
              </h2>
              <div className="grid gap-4 md:grid-cols-2">
                {result.rejected.map((o) => (
                  <RejectedCard key={o.id} opp={o} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
