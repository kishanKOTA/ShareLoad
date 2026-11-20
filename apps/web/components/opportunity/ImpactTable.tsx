import { fmtNumber } from "@/lib/format";
import type { Impact, ScenarioMetrics } from "@/lib/types";

const ROWS: { key: keyof ScenarioMetrics; label: string; unit: string; money?: boolean }[] = [
  { key: "distance_km", label: "Vehicle distance", unit: "km" },
  { key: "fuel_l", label: "Fuel", unit: "L" },
  { key: "co2_kg", label: "CO₂", unit: "kg" },
  { key: "cost_usd", label: "Fuel cost", unit: "$", money: true },
];

function fmt(v: number, money?: boolean) {
  return money
    ? v.toLocaleString("en-US", { style: "currency", currency: "USD" })
    : fmtNumber(v);
}

export default function ImpactTable({ impact }: { impact: Impact }) {
  const good = impact.recommended;
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Impact</h2>
        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200">
          Estimate
        </span>
        {!good && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-200">
            Not recommended
          </span>
        )}
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th className="py-2 pr-3 font-medium" />
              <th className="py-2 pr-3 text-right font-medium">Baseline</th>
              <th className="py-2 pr-3 text-right font-medium">Shared</th>
              <th className="py-2 text-right font-medium">Saved</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {ROWS.map(({ key, label, unit, money }) => (
              <tr key={key} className="border-b border-slate-100 last:border-0">
                <th scope="row" className="py-2 pr-3 text-left font-medium text-slate-700">
                  {key === "co2_kg" ? "Potential CO₂ avoided" : label}{" "}
                  <span className="font-normal text-slate-400">({unit})</span>
                </th>
                <td className="py-2 pr-3 text-right text-slate-600">{fmt(impact.baseline[key], money)}</td>
                <td className="py-2 pr-3 text-right text-slate-600">{fmt(impact.shared[key], money)}</td>
                <td
                  className={`py-2 text-right font-semibold ${
                    good ? "text-emerald-700" : "text-slate-700"
                  }`}
                >
                  {fmt(impact.net_saved[key], money)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        {fmtNumber(impact.reduction_pct)}% less total vehicle distance across both companies.
        Estimates only — not measured or guaranteed.
      </p>
    </section>
  );
}
