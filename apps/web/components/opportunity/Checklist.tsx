import { checkLabel, reasonLabel } from "@/lib/format";
import type { Check } from "@/lib/types";

export default function Checklist({ checks }: { checks: Check[] }) {
  const passed = checks.filter((c) => c.passed).length;
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Feasibility checks{" "}
        <span className="font-normal normal-case tracking-normal text-slate-400">
          ({passed} of {checks.length} passed)
        </span>
      </h2>
      <ul className="mt-3 divide-y divide-slate-100">
        {checks.map((c) => (
          <li key={c.name} className="flex gap-3 py-2 text-sm">
            <span
              aria-label={c.passed ? "passed" : "failed"}
              className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${
                c.passed ? "bg-emerald-600" : "bg-red-600"
              }`}
            >
              {c.passed ? "✓" : "✕"}
            </span>
            <div>
              <span className="font-medium text-slate-900">{checkLabel(c.name)}</span>
              {!c.passed && c.reason_code && (
                <span className="ml-2 text-red-700">{reasonLabel(c.reason_code)}</span>
              )}
              {c.detail && <p className="text-slate-600">{c.detail}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
