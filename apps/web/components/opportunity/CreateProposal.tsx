"use client";

import Link from "next/link";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useOrg } from "@/lib/org-context";
import type { Proposal } from "@/lib/types";

export default function CreateProposal({ opportunityId }: { opportunityId: string }) {
  const { orgId } = useOrg();
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState<{ status?: number; message: string } | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      setProposal(await api.createProposal(opportunityId, orgId));
    } catch (e) {
      setError(
        e instanceof ApiError
          ? { status: e.status, message: e.message }
          : { message: e instanceof Error ? e.message : String(e) },
      );
    } finally {
      setBusy(false);
    }
  }

  if (proposal) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
        Proposal <code>{proposal.id}</code> created — waiting for both companies to approve.{" "}
        <Link href="/proposals" className="font-medium underline">
          View in Proposals →
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        onClick={create}
        disabled={busy}
        className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:cursor-wait disabled:opacity-60"
      >
        {busy ? "Creating…" : "Create proposal"}
      </button>
      <span className="text-xs text-slate-500">
        Both companies must approve before anything is shared or booked.
      </span>
      {error && (
        <p className="w-full text-sm text-red-700">
          {error.status === 409 ? (
            <>
              {error.message.replace(/^409\s*/, "")}.{" "}
              <Link href="/proposals" className="font-medium underline">
                Go to Proposals →
              </Link>
            </>
          ) : error.status === 403 ? (
            "Only the trip owner or the shipment owner can propose this match."
          ) : (
            `Couldn't create the proposal: ${error.message}`
          )}
        </p>
      )}
    </div>
  );
}
