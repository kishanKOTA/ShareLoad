import type { ProposalStatus } from "./types";

/** Wording and colours for proposal statuses. Never say "dispatched": ShareLoad only records agreement. */
export const STATUS_META: Record<ProposalStatus, { label: string; className: string }> = {
  draft: { label: "Draft", className: "bg-slate-100 text-slate-700 ring-slate-200" },
  pending_approvals: {
    label: "Pending approvals",
    className: "bg-amber-50 text-amber-800 ring-amber-200",
  },
  partially_approved: {
    label: "Partially approved",
    className: "bg-sky-50 text-sky-800 ring-sky-200",
  },
  approved_for_external_coordination: {
    label: "Approved for external coordination",
    className: "bg-emerald-600 text-white ring-emerald-700",
  },
  rejected: { label: "Rejected", className: "bg-red-50 text-red-800 ring-red-200" },
};

export function statusMeta(status: string) {
  return (
    STATUS_META[status as ProposalStatus] ?? {
      label: status.replace(/_/g, " "),
      className: "bg-slate-100 text-slate-700 ring-slate-200",
    }
  );
}

export const FINAL_STATUSES = new Set<string>(["approved_for_external_coordination", "rejected"]);

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
}
