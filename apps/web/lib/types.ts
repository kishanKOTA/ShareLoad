// Mirrors services/api/app/schemas (see docs/PRD.md "Contracts").

export interface Location {
  name: string;
  lat: number;
  lon: number;
}

export interface TimeWindow {
  start: string;
  end: string;
}

export type CargoType =
  | "ambient"
  | "refrigerated"
  | "frozen"
  | "hazardous"
  | "fragile"
  | "oversized"
  | "other";

export interface Shipment {
  id: string;
  org_id: string;
  origin: Location | null;
  destination: Location | null;
  weight_kg: number | null;
  volume_m3: number | null;
  cargo_type: CargoType | null;
  hazardous: boolean | null;
  temp_min_c: number | null;
  temp_max_c: number | null;
  pickup_window: TimeWindow | null;
  delivery_window: TimeWindow | null;
  raw_text: string | null;
  extraction: { confidence: number; missing_fields: string[] } | null;
}

export interface Organization {
  id: string;
  name: string;
  region: string;
  is_sample: boolean;
}

export type ReasonCode =
  | "CAPACITY_WEIGHT_EXCEEDED"
  | "CAPACITY_VOLUME_EXCEEDED"
  | "CARGO_TEMP_UNSUPPORTED"
  | "HAZMAT_UNSUPPORTED"
  | "TIME_WINDOW_CONFLICT"
  | "DIRECTION_MISMATCH"
  | "DETOUR_EXCEEDS_LIMIT"
  | "MISSING_CRITICAL_FIELD";

export interface Check {
  name: string;
  passed: boolean;
  reason_code: ReasonCode | null;
  detail: string;
}

export interface RouteFeature {
  type: "Feature";
  id?: string;
  properties?: {
    id?: string;
    description?: string;
    stops?: string[];
    distance_km?: number;
    [key: string]: unknown;
  };
  geometry: unknown;
}

export interface RouteGeometry {
  type: "FeatureCollection";
  features: RouteFeature[];
}

export interface RouteScenario {
  description: string;
  distance_km: number;
  detour_km: number;
  geometry: RouteGeometry | null;
}

export interface ScenarioMetrics {
  distance_km: number;
  fuel_l: number;
  co2_kg: number;
  cost_usd: number;
}

export interface FormulaStep {
  label: string;
  formula: string;
  value: number;
  unit: string;
}

export interface Impact {
  baseline: ScenarioMetrics;
  shared: ScenarioMetrics;
  net_saved: ScenarioMetrics;
  reduction_pct: number;
  recommended: boolean;
  formula_trace: FormulaStep[];
  assumptions_version: string;
}

export interface Opportunity {
  id: string;
  trip_id: string;
  shipment_id: string;
  feasible: boolean;
  reason_codes: ReasonCode[];
  checks: Check[];
  baseline: RouteScenario | null;
  shared: RouteScenario | null;
  impact: Impact | null;
  score: number | null;
  explanation: string | null;
}

export interface ToolCall {
  name: string;
  args?: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
  [key: string]: unknown;
}

export interface AgentScanResult {
  candidates_considered: number;
  opportunities: Opportunity[];
  rejected: Opportunity[];
  agent_summary: string;
  tool_calls: ToolCall[];
  mode: "gemini" | "template" | string;
  model: string | null;
  fallback_reason: string | null;
  template_explanations: string[];
  template_summary: boolean;
  cached: boolean;
}

export type ProposalStatus =
  | "draft"
  | "pending_approvals"
  | "partially_approved"
  | "approved_for_external_coordination"
  | "rejected";

export interface Decision {
  org_id: string;
  decision: "approve" | "reject";
  comment: string | null;
  decided_at: string;
}

export interface AuditEvent {
  id: string;
  org_id: string | null;
  actor: "agent" | "user";
  event_type: string;
  entity: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Proposal {
  id: string;
  opportunity_id: string;
  status: ProposalStatus;
  version: number;
  snapshot: Opportunity;
  parties: string[];
  decisions: Decision[];
  created_by: string;
  created_at: string;
  updated_at: string;
}
