"use client";

import { useState } from "react";
import { fmtTime } from "@/lib/status";
import type { Decision } from "@/lib/types";

interface Props {
  orgName: string;
  role: string;
  decision: Decision | undefined;
  /** This card belongs to the org currently viewing. */
  isCurrentOrg: boolean;
  /** The proposal is already approved or rejected. */
  isFinal: boolean;
  onDecide: (decision: "approve" | "reject", comment: string) => Promise<void>;
}

export default function ApprovalCard({ orgName, role, decision, isCurrentOrg, isFinal, onDecide }: Props) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);

  const state = decision?.decision === "approve" ? "approved" : decision?.decision === "reject" ? "rejected" : "pending";
  const tone = {
    approved: { box: "border-emerald-200 bg-emerald-50", badge: "bg-emerald-600 text-white", label: "✓ Approved" },
    rejected: { box: "border-red-200 bg-red-50", badge: "bg-red-600 text-white", label: "✕ Rejected" },
    pending: { box: "border-slate-200 bg-white", badge: "bg-slate-100 text-slate-600 ring-1 ring-slate-200", label: "Pending" },
  }[state];

  async function decide(d: "approve" | "reject") {
    setBusy(d);
    try {
      await onDecide(d, comment);
    } finally {
      setBusy(null);
    }
  }

  const canDecide = isCurrentOrg && state === "pending" && !isFinal;

  return (
    <div className={`rounded-lg border p-3 ${tone.box} ${isCurrentOrg ? "ring-2 ring-slate-900/10" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-slate-900">
            {orgName}
            {isCurrentOrg && <span className="ml-1.5 text-xs font-normal text-slate-500">(you)</span>}
          </p>
          <p className="text-xs text-slate-500">{role}</p>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${tone.badge}`}>{tone.label}</span>
      </div>

      {decision && (
        <div className="mt-2 text-xs text-slate-600">
          <p>{fmtTime(decision.decided_at)}</p>
          {decision.comment && <p className="mt-1 text-sm italic text-slate-700">“{decision.comment}”</p>}
        </div>
      )}

      {canDecide && (
        <div className="mt-3 space-y-2">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Comment (optional)"
            rows={2}
            maxLength={500}
            className="w-full resize-y rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 placeholder:text-slate-400"
          />
          <div className="flex gap-2">
            <button
              onClick={() => decide("approve")}
              disabled={busy !== null}
              className="rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-60"
            >
              {busy === "approve" ? "Approving…" : "Approve"}
            </button>
            <button
              onClick={() => decide("reject")}
              disabled={busy !== null}
              className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
            >
              {busy === "reject" ? "Rejecting…" : "Reject"}
            </button>
          </div>
        </div>
      )}

      {!decision && !canDecide && (
        <p className="mt-2 text-xs text-slate-500">
          {isFinal ? "No decision needed — the proposal is closed." : "Waiting for their decision."}
        </p>
      )}
    </div>
  );
}
