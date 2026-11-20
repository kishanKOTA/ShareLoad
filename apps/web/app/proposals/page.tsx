"use client";

import { useOrg } from "@/lib/org-context";

export default function ProposalsPage() {
  const { currentOrg } = useOrg();

  return (
    <div>
      <h1 className="text-2xl font-semibold">Proposals</h1>
      <p className="mt-1 text-sm text-slate-600">
        Proposals {currentOrg ? `${currentOrg.name} is a party to` : ""} will appear here.
      </p>
    </div>
  );
}
