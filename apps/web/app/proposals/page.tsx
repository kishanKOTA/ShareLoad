"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import AuditTimeline from "@/components/proposals/AuditTimeline";
import ProposalCard from "@/components/proposals/ProposalCard";
import { api } from "@/lib/api";
import { useOrg } from "@/lib/org-context";
import type { AuditEvent, Proposal } from "@/lib/types";

export default function ProposalsPage() {
  const { orgId, currentOrg, organizations, dataVersion, notifyDataChanged } = useOrg();
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [p, e] = await Promise.all([api.proposals(orgId), api.auditEvents(orgId)]);
    return { p, e };
  }, [orgId]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    load()
      .then(({ p, e }) => {
        if (cancelled) return;
        setProposals(p);
        setEvents(e);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [load, dataVersion]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Proposals</h1>
        <p className="mt-1 text-sm text-slate-600">
          {currentOrg ? `Matches ${currentOrg.name} is a party to.` : " "} Both companies must approve before
          a match goes ahead.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Couldn&apos;t load proposals: {error}
        </div>
      )}

      {proposals === null && !error && <p className="text-sm text-slate-500">Loading proposals…</p>}

      {proposals?.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          No proposals yet.{" "}
          <Link href="/" className="font-medium text-slate-900 underline">
            Run a scan
          </Link>{" "}
          and create a proposal from a feasible match.
        </div>
      )}

      {proposals && proposals.length > 0 && (
        <div className="space-y-4">
          {proposals.map((p) => (
            <ProposalCard key={p.id} proposal={p} onChanged={notifyDataChanged} />
          ))}
        </div>
      )}

      {!error && <AuditTimeline events={events} orgs={organizations} />}
    </div>
  );
}
