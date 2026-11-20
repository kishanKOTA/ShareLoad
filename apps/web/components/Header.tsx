"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { shortOrgName, useOrg } from "@/lib/org-context";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/proposals", label: "Proposals" },
];

export default function Header() {
  const pathname = usePathname();
  const { orgId, setOrgId, organizations, loading, error } = useOrg();

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-2">
          <Link href="/" className="text-lg font-semibold tracking-tight text-slate-900">
            ShareLoad
          </Link>
          <span
            className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800"
            title="All organizations, trips and shipments are fictional demo data"
          >
            Sample data
          </span>
        </div>

        <nav className="flex items-center gap-1">
          {NAV.map(({ href, label }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                  active
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        <label className="ml-auto flex items-center gap-2 text-sm text-slate-600">
          <span>Viewing as</span>
          <select
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            disabled={loading || !!error || organizations.length === 0}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 disabled:opacity-60"
          >
            {organizations.length === 0 ? (
              <option value={orgId}>{loading ? "Loading…" : "Unavailable"}</option>
            ) : (
              organizations.map((o) => (
                <option key={o.id} value={o.id} title={o.name}>
                  {shortOrgName(o)}
                </option>
              ))
            )}
          </select>
        </label>
      </div>
    </header>
  );
}
