"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import type { Shipment } from "@/lib/types";

const MAX_CHARS = 20_000;

/** "2026-11-20T08:00:00-06:00" -> wall-clock parts in the string's own offset (not the browser's). */
function wallClock(iso: string) {
  const m = iso.match(/([+-]\d{2}):?(\d{2})$|Z$/);
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  let offsetMin = 0;
  if (m && m[0] !== "Z") offsetMin = (m[1].startsWith("-") ? -1 : 1) * (Math.abs(+m[1]) * 60 + +m[2]);
  const shifted = new Date(d.getTime() + offsetMin * 60_000);
  const opts = { timeZone: "UTC" } as const;
  return {
    day: shifted.toLocaleDateString("en-US", { ...opts, weekday: "short", month: "short", day: "numeric" }),
    time: shifted.toLocaleTimeString("en-US", { ...opts, hour: "numeric", minute: "2-digit" }),
    offset: m ? (m[0] === "Z" ? "UTC" : `UTC${m[1]}${m[2] === "00" ? "" : `:${m[2]}`}`) : "",
  };
}

function fmtWindow(w: { start: string; end: string }): string {
  const a = wallClock(w.start);
  const b = wallClock(w.end);
  if (!a || !b) return `${w.start} – ${w.end}`;
  const end = a.day === b.day ? b.time : `${b.day} ${b.time}`;
  return `${a.day}, ${a.time} – ${end} (${a.offset})`;
}

const CARGO_LABELS: Record<string, string> = {
  ambient: "Ambient (no temperature control)",
  refrigerated: "Refrigerated",
  frozen: "Frozen",
  hazardous: "Hazardous",
  fragile: "Fragile",
  oversized: "Oversized",
  other: "Other",
};

interface Row {
  field: string;
  label: string;
  value: string | null;
}

function rows(s: Shipment): Row[] {
  const temp =
    s.temp_min_c != null || s.temp_max_c != null
      ? `${s.temp_min_c ?? "?"} to ${s.temp_max_c ?? "?"} °C`
      : s.cargo_type && ["refrigerated", "frozen"].includes(s.cargo_type)
        ? null
        : "Not required";
  return [
    { field: "origin", label: "Pickup from", value: s.origin?.name ?? null },
    { field: "destination", label: "Deliver to", value: s.destination?.name ?? null },
    { field: "weight_kg", label: "Weight", value: s.weight_kg != null ? `${fmtNumber(s.weight_kg)} kg` : null },
    { field: "volume_m3", label: "Volume", value: s.volume_m3 != null ? `${fmtNumber(s.volume_m3)} m³` : null },
    { field: "cargo_type", label: "Cargo type", value: s.cargo_type ? (CARGO_LABELS[s.cargo_type] ?? s.cargo_type) : null },
    { field: "hazardous", label: "Hazardous", value: s.hazardous == null ? null : s.hazardous ? "Yes" : "No" },
    { field: "temp_min_c", label: "Temperature", value: temp },
    { field: "pickup_window", label: "Pickup window", value: s.pickup_window ? fmtWindow(s.pickup_window) : null },
    { field: "delivery_window", label: "Delivery window", value: s.delivery_window ? fmtWindow(s.delivery_window) : null },
  ];
}

function confidenceTone(c: number) {
  if (c >= 0.8) return "bg-emerald-50 text-emerald-800 ring-emerald-200";
  if (c >= 0.5) return "bg-amber-50 text-amber-800 ring-amber-200";
  return "bg-red-50 text-red-800 ring-red-200";
}

function friendlyError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 503)
      return "Email extraction isn't available right now — Gemini isn't set up on the server. You can still run a scan with the shipments on file.";
    if (e.status === 502)
      return "Gemini couldn't read this email just now. Try again in a moment, or check that the email describes the pickup, delivery, size and timing.";
    if (e.status === 422) return "The email text is empty or too long to extract.";
  }
  return `Couldn't reach the extraction service: ${e instanceof Error ? e.message : String(e)}`;
}

export default function EmailExtractionPanel({ orgId }: { orgId: string }) {
  const [text, setText] = useState("");
  const [hasShipments, setHasShipments] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Shipment | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Prefill with the email behind the shipment on file (ship-b for Lakeview).
  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setError(null);
    setText("");
    setHasShipments(false);
    api
      .shipments(orgId)
      .then((list) => {
        if (cancelled || list.length === 0) return;
        setHasShipments(true);
        const sample = list.find((s) => s.id === "ship-b" && s.raw_text) ?? list.find((s) => s.raw_text);
        setText(sample?.raw_text ?? "");
      })
      .catch(() => {
        // Not fatal: the panel just stays hidden.
      });
    return () => {
      cancelled = true;
    };
  }, [orgId]);

  if (!hasShipments) return null;

  async function extract() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.parseShipment(orgId, text));
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(false);
    }
  }

  const missing = new Set(result?.extraction?.missing_fields ?? []);
  // The temperature row stands for both temp fields.
  if (missing.has("temp_max_c")) missing.add("temp_min_c");
  const confidence = result?.extraction?.confidence;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">New shipment from email</h2>
        <span className="text-xs text-slate-500">Gemini reads the email; nothing is saved.</span>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={9}
        maxLength={MAX_CHARS}
        spellCheck={false}
        aria-label="Shipment email"
        className="mt-3 w-full resize-y rounded-md border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs leading-relaxed text-slate-800"
      />

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          onClick={extract}
          disabled={busy || !text.trim()}
          className="rounded-md bg-violet-700 px-4 py-2 text-sm font-medium text-white hover:bg-violet-600 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Extracting…" : "Extract with Gemini"}
        </button>
        {busy && <span className="text-xs text-slate-500">This can take a few seconds.</span>}
      </div>

      {error && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{error}</div>
      )}

      {result && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-900">Extracted shipment</h3>
            {confidence != null && (
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${confidenceTone(confidence)}`}>
                Confidence {Math.round(confidence * 100)}%
              </span>
            )}
            {missing.size > 0 ? (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-300">
                {result.extraction!.missing_fields.length} missing field
                {result.extraction!.missing_fields.length === 1 ? "" : "s"}
              </span>
            ) : (
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800 ring-1 ring-emerald-200">
                No missing fields
              </span>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <tbody>
                {rows(result).map((r) => {
                  const isMissing = missing.has(r.field) || r.value == null;
                  return (
                    <tr key={r.field} className={`border-b border-slate-100 last:border-0 ${isMissing ? "bg-amber-50" : ""}`}>
                      <th scope="row" className="w-40 py-2 pl-2 pr-3 text-left font-medium text-slate-600">
                        {r.label}
                      </th>
                      <td className="py-2 pr-2">
                        {isMissing ? (
                          <span className="font-medium text-amber-800">⚠ Missing — not found in the email</span>
                        ) : (
                          <span className="text-slate-900">{r.value}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="text-sm text-slate-600">Parsed into the same fields as the shipment on file. Run scan to find matches.</p>
        </div>
      )}
    </section>
  );
}
