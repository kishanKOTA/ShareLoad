import { checkLabel, reasonLabel } from "@/lib/format";
import type { Opportunity } from "@/lib/types";

export default function RejectedCard({ opp }: { opp: Opportunity }) {
  const failed = opp.checks.filter((c) => !c.passed);

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-200">
          Rejected
        </span>
        <span className="text-xs text-slate-500">
          Trip <code>{opp.trip_id}</code> + shipment <code>{opp.shipment_id}</code>
        </span>
      </div>

      <ul className="mt-3 space-y-1">
        {opp.reason_codes.map((code) => (
          <li key={code} className="flex flex-wrap items-baseline gap-2">
            <span className="text-sm font-medium text-slate-900">{reasonLabel(code)}</span>
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
              {code}
            </code>
          </li>
        ))}
      </ul>

      {failed.length > 0 && (
        <dl className="mt-3 space-y-1.5 border-t border-slate-100 pt-3 text-sm">
          {failed.map((c) => (
            <div key={c.name} className="flex flex-wrap gap-x-2">
              <dt className="font-medium text-slate-700">{checkLabel(c.name)}:</dt>
              <dd className="text-slate-600">{c.detail}</dd>
            </div>
          ))}
        </dl>
      )}

      {opp.explanation && <p className="mt-3 text-sm text-slate-600">{opp.explanation}</p>}
    </article>
  );
}
