"use client";

import { API_URL } from "@/lib/api";
import { useOrg } from "@/lib/org-context";

export default function OverviewPage() {
  const { organizations, currentOrg, loading, error, reload } = useOrg();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="mt-1 text-sm text-slate-600">
          {currentOrg ? `Viewing as ${currentOrg.name} · ${currentOrg.region}` : " "}
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Organizations
        </h2>

        {loading && <p className="mt-3 text-sm text-slate-600">Loading organizations…</p>}

        {error && (
          <div className="mt-3 text-sm text-red-700">
            <p>
              Couldn&apos;t reach the API at <code>{API_URL}</code>: {error}
            </p>
            <button
              onClick={reload}
              className="mt-2 rounded-md border border-red-300 px-3 py-1 hover:bg-red-50"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !error && (
          <ul className="mt-3 divide-y divide-slate-100" data-testid="org-list">
            {organizations.map((o) => (
              <li key={o.id} className="flex items-center justify-between py-2 text-sm">
                <span className="font-medium">{o.name}</span>
                <span className="text-slate-500">{o.region}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
