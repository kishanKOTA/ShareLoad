"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Checklist from "@/components/opportunity/Checklist";
import CreateProposal from "@/components/opportunity/CreateProposal";
import ImpactTable from "@/components/opportunity/ImpactTable";
import Methodology from "@/components/opportunity/Methodology";
import { api, ApiError } from "@/lib/api";
import { fmtNumber, reasonLabel, sharedRouteStops } from "@/lib/format";
import { useOrg } from "@/lib/org-context";
import type { Opportunity } from "@/lib/types";

const RouteMap = dynamic(() => import("@/components/opportunity/RouteMap"), {
  ssr: false,
  loading: () => <div className="h-[420px] animate-pulse rounded-lg bg-slate-200" />,
});

export default function OpportunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { orgId } = useOrg();
  const [opp, setOpp] = useState<Opportunity | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setOpp(null);
    setError(null);
    api
      .opportunity(decodeURIComponent(id), orgId)
      .then((o) => !cancelled && setOpp(o))
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? "This opportunity wasn't found. Run a scan from the Overview first."
            : e instanceof Error
              ? e.message
              : String(e),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [id, orgId]);

  const back = (
    <Link href="/" className="text-sm text-slate-500 hover:text-slate-900">
      ← Overview
    </Link>
  );

  if (error) {
    return (
      <div className="space-y-3">
        {back}
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>
      </div>
    );
  }
  if (!opp) {
    return (
      <div className="space-y-3">
        {back}
        <p className="text-sm text-slate-500">Loading opportunity…</p>
      </div>
    );
  }

  const stops = sharedRouteStops(opp);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        {back}
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
              opp.feasible
                ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
                : "bg-slate-100 text-slate-700 ring-slate-200"
            }`}
          >
            {opp.feasible ? "Feasible match" : "Rejected"}
          </span>
          <code className="text-xs text-slate-500">{opp.id}</code>
        </div>
        <h1 className="text-2xl font-semibold">
          {stops ? stops.join(" → ") : `${opp.trip_id} + ${opp.shipment_id}`}
        </h1>
        <p className="text-sm text-slate-600">
          Trip <code>{opp.trip_id}</code> carries shipment <code>{opp.shipment_id}</code>
          {opp.shared ? ` · ${fmtNumber(opp.shared.detour_km)} km detour` : ""}
        </p>
        {!opp.feasible && (
          <ul className="text-sm text-red-700">
            {opp.reason_codes.map((c) => (
              <li key={c}>{reasonLabel(c)}</li>
            ))}
          </ul>
        )}
      </div>

      {opp.explanation && (
        <section className="rounded-lg border border-sky-200 bg-sky-50 p-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-sky-900">
            Agent explanation
          </h2>
          <p className="mt-2 text-[15px] leading-relaxed text-slate-900">{opp.explanation}</p>
        </section>
      )}

      {(opp.baseline?.geometry || opp.shared?.geometry) && <RouteMap opp={opp} />}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 [&>*]:min-w-0">
        <Checklist checks={opp.checks} />
        {opp.impact && <ImpactTable impact={opp.impact} />}
      </div>

      <Methodology opp={opp} />

      {opp.feasible && <CreateProposal key={`${opp.id}:${orgId}`} opportunityId={opp.id} />}
    </div>
  );
}
