import { fmtNumber } from "@/lib/format";
import type { Opportunity } from "@/lib/types";

export default function Methodology({ opp }: { opp: Opportunity }) {
  const impact = opp.impact;
  if (!impact) return null;
  return (
    <details className="group rounded-lg border border-slate-200 bg-white">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium text-slate-800 [&::-webkit-details-marker]:hidden">
        <span className="inline-block transition-transform group-open:rotate-90">▸</span>
        Assumptions &amp; methodology
        <span className="text-xs font-normal text-slate-500">
          (assumptions {impact.assumptions_version})
        </span>
      </summary>
      <div className="space-y-4 px-4 pb-4 text-sm text-slate-700">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            We compare total vehicle distance across both businesses under the same assumptions.
          </li>
          {opp.baseline && (
            <li>
              <b>Baseline</b>: {opp.baseline.description} ({fmtNumber(opp.baseline.distance_km)} km).
            </li>
          )}
          {opp.shared && (
            <li>
              <b>Shared</b>: {opp.shared.description} ({fmtNumber(opp.shared.distance_km)} km,
              including a {fmtNumber(opp.shared.detour_km)} km detour).
            </li>
          )}
          <li>One fuel rate for loaded and empty running (a simplification).</li>
          <li>Not included: driver time, tolls, handling, insurance, contract charges.</li>
          <li>Routes are cached road routes from OpenStreetMap (OSRM).</li>
        </ul>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-2 pr-3 font-medium">Step</th>
                <th className="py-2 pr-3 font-medium">Formula</th>
                <th className="py-2 text-right font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {impact.formula_trace.map((s, i) => (
                <tr key={i} className="border-b border-slate-100 last:border-0">
                  <td className="py-1.5 pr-3 text-slate-700">{s.label}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs text-slate-600">{s.formula}</td>
                  <td className="py-1.5 text-right tabular-nums text-slate-900">
                    {s.unit === "USD" ? `$${fmtNumber(s.value, 2)}` : `${fmtNumber(s.value, 2)} ${s.unit}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}
