import type { Opportunity, ReasonCode } from "./types";

/** Plain-language versions of the validator's reason codes. */
export const REASON_LABELS: Record<ReasonCode, string> = {
  CAPACITY_WEIGHT_EXCEEDED: "Too heavy for the space left on the truck",
  CAPACITY_VOLUME_EXCEEDED: "Too bulky for the space left on the truck",
  CARGO_TEMP_UNSUPPORTED: "Truck can't keep the cargo at the right temperature",
  HAZMAT_UNSUPPORTED: "Truck isn't cleared to carry hazardous goods",
  TIME_WINDOW_CONFLICT: "Truck can't make the pickup or delivery time",
  DIRECTION_MISMATCH: "Shipment goes a different way than the truck",
  DETOUR_EXCEEDS_LIMIT: "Detour to pick up and drop off is too long",
  MISSING_CRITICAL_FIELD: "Shipment is missing details needed to check it",
};

export function reasonLabel(code: string): string {
  return REASON_LABELS[code as ReasonCode] ?? code.replace(/_/g, " ").toLowerCase();
}

const CHECK_LABELS: Record<string, string> = {
  critical_fields: "Required details",
  weight_capacity: "Weight",
  volume_capacity: "Volume",
  cargo_temperature: "Temperature",
  hazmat: "Hazardous goods",
  direction: "Direction",
  detour: "Detour",
  pickup_window: "Pickup time",
  delivery_window: "Delivery time",
};

export function checkLabel(name: string): string {
  if (CHECK_LABELS[name]) return CHECK_LABELS[name];
  const s = name.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function fmtNumber(n: number, maxFractionDigits = 1): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: maxFractionDigits });
}

/** Turn "Customer drop, West Loop, Chicago, IL" into "West Loop". */
function shortStop(stop: string): string {
  const parts = stop.split(",").map((p) => p.trim());
  // "<what>, <place>, <city>, <state>" -> place; "<what>, <city>, <state>" -> what
  return parts.length >= 4 ? parts[1] : parts[0];
}

/**
 * Stops on the shared route: the feature in the shared geometry that the
 * baseline doesn't have (the leg that picks up and drops off the shipment).
 */
export function sharedRouteStops(opp: Opportunity): string[] | null {
  const shared = opp.shared?.geometry?.features ?? [];
  const baselineIds = new Set(
    (opp.baseline?.geometry?.features ?? []).map((f) => f.properties?.id ?? f.id),
  );
  const leg =
    shared.find((f) => !baselineIds.has(f.properties?.id ?? f.id)) ?? shared[shared.length - 1];
  const stops = leg?.properties?.stops;
  return stops && stops.length ? stops.map(shortStop) : null;
}
