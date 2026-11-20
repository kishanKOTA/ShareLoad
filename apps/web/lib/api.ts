import type { AgentScanResult, AuditEvent, Opportunity, Organization, Proposal } from "./types";

export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"
).replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Call the ShareLoad API. `orgId` is sent as `X-Org-Id`, which stands in for
 * auth: org-scoped routes return 403/422 without a matching header.
 */
export async function apiFetch<T>(
  path: string,
  orgId?: string | null,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (orgId) headers.set("X-Org-Id", orgId);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, `${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

export const api = {
  organizations: (orgId?: string | null) =>
    apiFetch<Organization[]>("/organizations", orgId),

  /** Run the agent scan. `useCached` returns the last saved Gemini run if the data is unchanged. */
  scan: (orgId: string | null, useCached: boolean) =>
    apiFetch<AgentScanResult>(
      `/opportunities/scan?use_cached=${useCached ? "true" : "false"}`,
      orgId,
      { method: "POST" },
    ),

  opportunity: (id: string, orgId?: string | null) =>
    apiFetch<Opportunity>(`/opportunities/${encodeURIComponent(id)}`, orgId),

  /** 403 if the org isn't a party; 409 if not feasible or already proposed. */
  createProposal: (opportunityId: string, orgId: string) =>
    apiFetch<Proposal>(`/opportunities/${encodeURIComponent(opportunityId)}/proposals`, orgId, {
      method: "POST",
    }),

  /** Proposals the org is a party to. */
  proposals: (orgId: string) => apiFetch<Proposal[]>("/proposals", orgId),

  /** 403 if not a party; 409 if already final or this org already decided. */
  decide: (proposalId: string, orgId: string, decision: "approve" | "reject", comment?: string) =>
    apiFetch<Proposal>(`/proposals/${encodeURIComponent(proposalId)}/decision`, orgId, {
      method: "POST",
      body: JSON.stringify({ decision, comment: comment?.trim() || null }),
    }),

  /** Audit events visible to the org, oldest first. */
  auditEvents: (orgId: string) => apiFetch<AuditEvent[]>("/audit-events", orgId),

  /** Clear proposals, audit events and scan caches. */
  resetDemo: () => apiFetch<{ status: string }>("/demo/reset", null, { method: "POST" }),
};
