import { fmtNumber } from "@/lib/format";
import { orgLabel } from "@/lib/org-context";
import { fmtTime, statusMeta } from "@/lib/status";
import type { AuditEvent, Organization } from "@/lib/types";

function describe(e: AuditEvent, orgs: Organization[]): { title: string; detail?: string } {
  const p = e.payload as Record<string, unknown>;
  const who = orgLabel(orgs, e.org_id);
  const entity = e.entity.replace(/^proposal:/, "");
  switch (e.event_type) {
    case "scan.completed": {
      const found = (p.opportunity_ids as unknown[] | undefined)?.length ?? 0;
      const rejected = (p.rejected_ids as unknown[] | undefined)?.length ?? 0;
      const mode = p.mode === "gemini" ? "Gemini" : "template";
      return {
        title: "Agent scan completed",
        detail: `${fmtNumber(Number(p.candidates_considered ?? 0))} candidates checked · ${found} feasible · ${rejected} rejected · ${mode}${p.cached ? " (cached)" : ""}`,
      };
    }
    case "proposal.created":
      return {
        title: `${who} proposed ${entity}`,
        detail: p.opportunity_id ? `For opportunity ${String(p.opportunity_id)}` : undefined,
      };
    case "proposal.approved":
    case "proposal.rejected": {
      const verb = e.event_type === "proposal.approved" ? "approved" : "rejected";
      const parts = [`Status now: ${statusMeta(String(p.status ?? "")).label}`];
      if (p.comment) parts.unshift(`“${String(p.comment)}”`);
      return { title: `${who} ${verb} ${entity}`, detail: parts.join(" · ") };
    }
    default:
      return { title: `${e.event_type} · ${e.entity}` };
  }
}

const DOT: Record<string, string> = {
  "scan.completed": "bg-violet-500",
  "proposal.created": "bg-sky-500",
  "proposal.approved": "bg-emerald-500",
  "proposal.rejected": "bg-red-500",
};

export default function AuditTimeline({ events, orgs }: { events: AuditEvent[]; orgs: Organization[] }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Audit trail <span className="font-normal normal-case tracking-normal text-slate-400">({events.length})</span>
      </h2>
      {events.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">No events yet. Scans, proposals and decisions will appear here.</p>
      ) : (
        <ol className="relative mt-3 border-l border-slate-200">
          {events.map((e) => {
            const { title, detail } = describe(e, orgs);
            return (
              <li key={e.id} className="ml-4 py-2">
                <span
                  className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${DOT[e.event_type] ?? "bg-slate-400"}`}
                  aria-hidden
                />
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="font-medium text-slate-900">{title}</span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                      e.actor === "agent" ? "bg-violet-50 text-violet-700" : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {e.actor === "agent" ? "Agent" : "User"}
                  </span>
                  <span className="text-xs text-slate-400">{fmtTime(e.created_at)}</span>
                </div>
                {detail && <p className="mt-0.5 text-sm text-slate-600">{detail}</p>}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
