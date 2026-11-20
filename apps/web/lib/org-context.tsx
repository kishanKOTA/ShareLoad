"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api } from "./api";
import type { Organization } from "./types";

export const DEFAULT_ORG_ID = "northstar";
const STORAGE_KEY = "shareload.orgId";

interface OrgContextValue {
  orgId: string;
  setOrgId: (id: string) => void;
  organizations: Organization[];
  currentOrg: Organization | undefined;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

const OrgContext = createContext<OrgContextValue | null>(null);

export function OrgProvider({ children }: { children: React.ReactNode }) {
  const [orgId, setOrgIdState] = useState(DEFAULT_ORG_ID);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Restore the last selected org after hydration.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) setOrgIdState(saved);
    } catch {
      // storage unavailable; keep default
    }
  }, []);

  const setOrgId = useCallback((id: string) => {
    setOrgIdState(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .organizations()
      .then((orgs) => {
        if (!cancelled) setOrganizations(orgs);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // Fall back to the first known org if the stored id isn't valid.
  useEffect(() => {
    if (organizations.length && !organizations.some((o) => o.id === orgId)) {
      setOrgId(organizations[0].id);
    }
  }, [organizations, orgId, setOrgId]);

  const value = useMemo<OrgContextValue>(
    () => ({
      orgId,
      setOrgId,
      organizations,
      currentOrg: organizations.find((o) => o.id === orgId),
      loading,
      error,
      reload: () => setAttempt((n) => n + 1),
    }),
    [orgId, setOrgId, organizations, loading, error],
  );

  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>;
}

export function useOrg(): OrgContextValue {
  const ctx = useContext(OrgContext);
  if (!ctx) throw new Error("useOrg must be used inside <OrgProvider>");
  return ctx;
}

/** "NorthStar Regional Freight" -> "NorthStar" for compact UI. */
export function shortOrgName(org: Organization): string {
  return org.name.split(" ")[0];
}
