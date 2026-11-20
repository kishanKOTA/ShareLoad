"use client";

import L from "leaflet";
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip } from "react-leaflet";
import { lineLatLngs, routeStops, splitRoutes, type LatLng } from "@/lib/geo";
import type { Opportunity } from "@/lib/types";

// The routes share long stretches of highway, so the shared route is drawn
// wide underneath and the dashed baseline thin on top: both stay visible.
const BASELINE_STYLE = { color: "#334155", weight: 2.5, opacity: 0.9, dashArray: "6 8" };
const SHARED_STYLE = { color: "#16a34a", weight: 8, opacity: 0.75 };

function pinIcon(letter: string, bg: string) {
  return L.divIcon({
    className: "",
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    html: `<div style="width:28px;height:28px;border-radius:9999px;background:${bg};color:#fff;font:600 13px/28px system-ui,sans-serif;text-align:center;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35)">${letter}</div>`,
  });
}
const PICKUP_ICON = pinIcon("P", "#15803d");
const DROP_ICON = pinIcon("D", "#1d4ed8");

export default function RouteMap({ opp }: { opp: Opportunity }) {
  const { baseline, shared, sharedOnly } = splitRoutes(opp);

  // The shared-only leg runs: truck start -> pickup(s) -> drop(s) -> truck end.
  const stops = sharedOnly.flatMap(routeStops);
  const inner = stops.length >= 3 ? stops.slice(1, -1) : [];
  const pickup = inner[0];
  const drop = inner.length > 1 ? inner[inner.length - 1] : undefined;
  const truckEnds = stops.length >= 3 ? [stops[0], stops[stops.length - 1]] : [];

  const all: LatLng[] = [...baseline, ...shared].flatMap(lineLatLngs);
  if (!all.length) {
    return (
      <div className="flex h-96 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-500">
        No route geometry for this opportunity.
      </div>
    );
  }
  const bounds = L.latLngBounds(all).pad(0.08);

  return (
    <div className="relative h-[420px] overflow-hidden rounded-lg border border-slate-200">
      <MapContainer bounds={bounds} scrollWheelZoom={false} className="h-full w-full">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {shared.map((f, i) => (
          <Polyline key={`s-${i}`} positions={lineLatLngs(f)} pathOptions={SHARED_STYLE}>
            <Tooltip sticky>Shared: {f.properties?.description ?? "route"}</Tooltip>
          </Polyline>
        ))}
        {baseline.map((f, i) => (
          <Polyline key={`b-${i}`} positions={lineLatLngs(f)} pathOptions={BASELINE_STYLE}>
            <Tooltip sticky>Baseline: {f.properties?.description ?? "route"}</Tooltip>
          </Polyline>
        ))}
        {truckEnds.map((s, i) => (
          <CircleMarker
            key={`t-${i}`}
            center={s.position}
            radius={6}
            pathOptions={{ color: "#fff", weight: 2, fillColor: "#334155", fillOpacity: 1 }}
          >
            <Tooltip>{s.name}</Tooltip>
          </CircleMarker>
        ))}
        {pickup && (
          <Marker position={pickup.position} icon={PICKUP_ICON}>
            <Tooltip>Pickup: {pickup.name}</Tooltip>
          </Marker>
        )}
        {drop && (
          <Marker position={drop.position} icon={DROP_ICON}>
            <Tooltip>Drop-off: {drop.name}</Tooltip>
          </Marker>
        )}
      </MapContainer>

      <div className="pointer-events-none absolute bottom-6 left-2 z-[1000] rounded-md bg-white/95 px-3 py-2 text-xs text-slate-700 shadow ring-1 ring-slate-200">
        <LegendLine color="#334155" dashed label="Baseline (each company drives separately)" />
        <LegendLine color="#16a34a" label="Shared route" />
        <LegendDot bg="#15803d" letter="P" label="Pickup" />
        <LegendDot bg="#1d4ed8" letter="D" label="Drop-off" />
        <LegendDot bg="#334155" label="Truck start / end" />
      </div>
    </div>
  );
}

function LegendLine({ color, dashed, label }: { color: string; dashed?: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <svg width="28" height="6" aria-hidden>
        <line
          x1="0" y1="3" x2="28" y2="3"
          stroke={color}
          strokeWidth={dashed ? 2.5 : 6}
          strokeDasharray={dashed ? "5 4" : undefined}
        />
      </svg>
      {label}
    </div>
  );
}

function LegendDot({ bg, letter, label }: { bg: string; letter?: string; label: string }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <span className="flex w-7 justify-center">
        <span
          className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-semibold text-white ring-2 ring-white"
          style={{ background: bg }}
        >
          {letter}
        </span>
      </span>
      {label}
    </div>
  );
}
