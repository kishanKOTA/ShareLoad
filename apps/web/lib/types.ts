// Mirrors services/api/app/schemas (see docs/PRD.md "Contracts").

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
