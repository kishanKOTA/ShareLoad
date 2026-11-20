import Link from "next/link";
import { fmtNumber, sharedRouteStops } from "@/lib/format";
import type { Opportunity } from "@/lib/types";

function Stat({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-xl font-semibold tabular-nums text-slate-900">
        {value} <span className="text-sm font-normal text-slate-500">{unit}</span>
      </dd>
    </div>
  );
}

export default function OpportunityCard({ opp }: { opp: Opportunity }) {
  const stops = sharedRouteStops(opp);
  const impact = opp.impact;
  const recommended = impact?.recommended ?? true;

  return (
    <article className="rounded-lg border border-emerald-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              recommended
                ? "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200"
                : "bg-slate-100 text-slate-700 ring-1 ring-slate-200"
            }`}
          >
            {recommended ? "Feasible match" : "Feasible · not recommended"}
          </span>
          <h3 className="mt-2 text-base font-semibold text-slate-900">
            {stops ? stops.join(" → ") : (opp.shared?.description ?? opp.id)}
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Trip <code>{opp.trip_id}</code> carries shipment <code>{opp.shipment_id}</code>
            {opp.shared ? ` · ${fmtNumber(opp.shared.detour_km)} km detour` : ""}
          </p>
        </div>
        <Link
          href={`/opportunities/${encodeURIComponent(opp.id)}`}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          View details
        </Link>
      </div>

      {impact && (
        <>
          <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Stat label="Distance saved" value={fmtNumber(impact.net_saved.distance_km)} unit="km" />
            <Stat label="Fuel saved" value={fmtNumber(impact.net_saved.fuel_l)} unit="L" />
            <Stat
              label="Potential CO₂ avoided (estimate)"
              value={fmtNumber(impact.net_saved.co2_kg)}
              unit="kg"
            />
          </dl>
          <p className="mt-3 text-xs text-slate-500">
            {fmtNumber(impact.reduction_pct)}% less vehicle distance than both companies driving
            separately ({fmtNumber(impact.baseline.distance_km)} km →{" "}
            {fmtNumber(impact.shared.distance_km)} km).
          </p>
        </>
      )}

      {opp.explanation && (
        <p className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-700">
          {opp.explanation}
        </p>
      )}
    </article>
  );
}
