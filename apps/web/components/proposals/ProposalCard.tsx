"use client";

import Link from "next/link";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtNumber, sharedRouteStops } from "@/lib/format";
import { orgLabel, useOrg } from "@/lib/org-context";
import { FINAL_STATUSES, fmtTime, statusMeta } from "@/lib/status";
import type { Proposal } from "@/lib/types";
import ApprovalCard from "./ApprovalCard";

const ROLES = ["Carrier · owns the truck trip", "Shipper · owns the shipment"];

export default function ProposalCard({ proposal, onChanged }: { proposal: Proposal; onChanged: () => void }) {
  const { orgId, organizations } = useOrg();
  const [error, setError] = useState<string | null>(null);

  const opp = proposal.snapshot;
  const stops = sharedRouteStops(opp);
  const saved = opp.impact?.net_saved;
  const meta = statusMeta(proposal.status);
  const isFinal = FINAL_STATUSES.has(proposal.status);

  async function decide(decision: "approve" | "reject", comment: string) {
    setError(null);
    try {
      await api.decide(proposal.id, orgId, decision, comment);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? `${e.message.replace(/^409\s*/, "")}. Showing the latest state.`
          : `Couldn't record the decision: ${e instanceof Error ? e.message : String(e)}`,
      );
    }
    onChanged();
  }

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${meta.className}`}>
              {meta.label}
            </span>
            <code className="text-xs text-slate-500">{proposal.id}</code>
          </div>
          <h2 className="mt-2 text-base font-semibold text-slate-900">
            {stops ? stops.join(" → ") : `${opp.trip_id} + ${opp.shipment_id}`}
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Proposed by {orgLabel(organizations, proposal.created_by)} · {fmtTime(proposal.created_at)} ·{" "}
            <Link href={`/opportunities/${encodeURIComponent(proposal.opportunity_id)}`} className="underline hover:text-slate-900">
              view opportunity
            </Link>
          </p>
        </div>
        {saved && (
          <dl className="grid grid-cols-3 gap-4 text-right">
            <div>
              <dt className="text-xs text-slate-500">Distance saved</dt>
              <dd className="font-semibold tabular-nums">{fmtNumber(saved.distance_km)} km</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Fuel saved</dt>
              <dd className="font-semibold tabular-nums">{fmtNumber(saved.fuel_l)} L</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">CO₂ avoided (est.)</dt>
              <dd className="font-semibold tabular-nums">{fmtNumber(saved.co2_kg)} kg</dd>
            </div>
          </dl>
        )}
      </div>

      {proposal.status === "approved_for_external_coordination" && (
        <div className="mt-4 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
          <b>Approved for external coordination.</b> Both companies agreed. They now arrange the pickup
          directly — ShareLoad doesn&apos;t book or move the truck.
        </div>
      )}
      {proposal.status === "rejected" && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
          <b>Rejected.</b> This match won&apos;t go ahead. Nothing was shared beyond the proposal.
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {proposal.parties.map((party, i) => (
          <ApprovalCard
            key={party}
            orgName={orgLabel(organizations, party)}
            role={ROLES[i] ?? "Party"}
            decision={proposal.decisions.find((d) => d.org_id === party)}
            isCurrentOrg={party === orgId}
            isFinal={isFinal}
            onDecide={decide}
          />
        ))}
      </div>

      {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
    </article>
  );
}
