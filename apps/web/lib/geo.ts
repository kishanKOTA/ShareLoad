import type { Opportunity, RouteFeature } from "./types";

export type LatLng = [number, number];

/** GeoJSON [lon, lat] LineString coordinates -> Leaflet [lat, lon]. */
export function lineLatLngs(feature: RouteFeature): LatLng[] {
  const g = feature.geometry as { type?: string; coordinates?: number[][] } | null;
  if (!g || g.type !== "LineString" || !g.coordinates) return [];
  return g.coordinates.map(([lon, lat]) => [lat, lon]);
}

function haversineKm([lat1, lon1]: LatLng, [lat2, lon2]: LatLng): number {
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

export interface Stop {
  name: string;
  position: LatLng;
}

/**
 * Position each named stop on a route. The API gives stop names and per-leg
 * distances (legs_km) but not stop coordinates, so we walk the line to each
 * cumulative leg distance (scaled to the line's own length).
 */
export function routeStops(feature: RouteFeature): Stop[] {
  const names = feature.properties?.stops ?? [];
  const pts = lineLatLngs(feature);
  if (!names.length || pts.length < 2) return [];

  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + haversineKm(pts[i - 1], pts[i]));
  const lineKm = cum[cum.length - 1];

  const legs = (feature.properties?.legs_km as number[] | undefined) ?? [];
  const legTotal = legs.reduce((a, b) => a + b, 0);
  const targets = [0];
  if (legs.length === names.length - 1 && legTotal > 0) {
    let acc = 0;
    for (const l of legs) targets.push(((acc += l) / legTotal) * lineKm);
  } else {
    // No usable legs: spread stops evenly.
    for (let i = 1; i < names.length; i++) targets.push((i / (names.length - 1)) * lineKm);
  }

  let j = 0;
  return names.map((name, i) => {
    const t = targets[i];
    while (j < cum.length - 1 && cum[j + 1] < t) j++;
    const seg = cum[j + 1] - cum[j];
    const f = seg > 0 ? Math.min(1, Math.max(0, (t - cum[j]) / seg)) : 0;
    const a = pts[j];
    const b = pts[Math.min(j + 1, pts.length - 1)];
    return { name, position: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f] };
  });
}

const featureId = (f: RouteFeature) => f.properties?.id ?? f.id;

/** Split an opportunity's routes for the map. */
export function splitRoutes(opp: Opportunity) {
  const baseline = opp.baseline?.geometry?.features ?? [];
  const shared = opp.shared?.geometry?.features ?? [];
  const baselineIds = new Set(baseline.map(featureId));
  // The leg(s) that only exist in the shared plan: the detour that carries the shipment.
  const sharedOnly = shared.filter((f) => !baselineIds.has(featureId(f)));
  return { baseline, shared, sharedOnly };
}
