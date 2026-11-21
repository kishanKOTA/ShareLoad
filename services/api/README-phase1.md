# Phase 1 platform backend

Python 3.11+ is required. Run these commands from the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r services/api/requirements.txt
cp .env.example .env
cd services/api
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use an available Python 3.11+ interpreter in the first command. Set the Gemini
key privately in the root `.env` for extraction. No key is needed for read APIs,
startup, SQLite initialization or tests. `/docs` exposes OpenAPI.
All fixture records represent fictional sample data.

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/organizations
curl -H 'X-Org-Id: northstar' http://localhost:8000/api/v1/organizations/northstar/vehicles
curl -H 'X-Org-Id: lakeview' http://localhost:8000/api/v1/organizations/lakeview/shipments
curl -X POST 'http://localhost:8000/api/v1/ingest/shipments/parse?require_complete=true' \
  -H 'X-Org-Id: lakeview' -H 'Content-Type: application/json' \
  -d '{"raw_text":"Need a shipment moved; details still to be confirmed."}'
```

Run all existing and new tests from `services/api`:

```bash
../../.venv/bin/python -m pytest -q
```

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | empty | Server-side extraction credential; never exposed to the browser |
| `GEMINI_MODEL` | `gemini-flash-latest` | Pin a provider model for a repeatable demo |
| `GEMINI_TIMEOUT_MS` | `30000` | Per-request timeout; provider retries disabled, malformed output retried once by extraction |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated exact HTTP(S) origins; wildcard/path rejected; empty disables cross-origin access |
| `SHARELOAD_DATA_DIR` | `data/demo` | Validated organization/vehicle/trip/shipment fixtures |
| `SHARELOAD_DATABASE_PATH` | `services/api/shareload.db` | SQLite file created and migrated on startup |

Relative paths resolve from the repository root. Process environment overrides
`.env`. Restart after configuration or fixture changes. Startup fails if fixtures,
references, configuration or SQLite migrations are invalid. Read APIs use a
validated fixture snapshot, never silently skip invalid records.

## Phase 1 endpoints and errors

- `GET /health` and compatibility alias `GET /api/v1/health`: `{"status":"ok"}`.
- `GET /api/v1/organizations`: both organizations, no header required (switcher).
- `GET /api/v1/organizations/{id}/vehicles`, `/trips`, `/shipments`: only that
  organization's records, including an empty array when none exist.
- `POST /api/v1/ingest/shipments/parse`: body `{"raw_text":"..."}`; returns a
  schema-valid `Shipment` with nested `extraction.confidence` and `missing_fields`.
  Server generates the ID and org context; extracted data is never persisted.

`X-Org-Id` is a **demo workspace selector, not production authentication**.
An unknown path org gives 404; a blank header gives 400; a different/unknown
caller gives 403; a missing required header gives 422, preserving existing
FastAPI tests and frontend expectations. Request validation also gives 422 for
blank/oversized text, invalid JSON or unknown request fields. Errors have `detail`;
request validation uses FastAPI's standard field-error array.

A missing critical extraction field stays null. Default behavior preserves the
frozen partial-Shipment response: HTTP 200 includes `extraction.missing_fields`,
`X-Manual-Entry-Required: true` and JSON field errors in
`X-Shipment-Validation-Errors` (both exposed through CORS). This is an incomplete
extraction requiring manual completion, never a ready-to-match record.
Use `?require_complete=true` to receive an explicit HTTP 422 body with `detail`,
`code: MISSING_CRITICAL_FIELD`, `missing_fields`, `errors` and a partial `shipment`.
Refrigerated/frozen shipments also require both temperature bounds.

The provider gets at most two generation calls for malformed JSON/schema output.
Provider/network/quota errors do not trigger an application retry. Unavailable
configuration gives 503; provider failures or invalid output twice give 502.
These errors instruct manual entry and do not return provider exception text,
credentials, or raw prompts. The manual fallback is the partial JSON plus field
errors for an operator to complete; this phase does not add a manual-entry UI or
shipment-write endpoint. Existing fixture reads remain available without Gemini.

Times must carry ISO-8601 offsets; units remain km/kg/m3/litres. Extraction may
convert explicitly stated units and resolve dates from a message date, but must
not invent missing dates, timezone, hazard status or coordinates. Locations
without explicit coordinates are null; there is no geocoder in this phase.
LLM output remains untrusted and needs human review; structural validation does
not establish the factual truth of extracted values.

## Frontend contract findings

Inspected `apps/web/lib/api.ts`, `lib/types.ts` and every component/page request.
No frontend, demo fixture or frozen schema files were changed.

- The client expects a direct `Shipment`, not a response envelope. Its confidence
  and missing fields live inside `extraction`; this is preserved.
- The client documents missing org context as 403/422, so missing headers remain
  422 rather than silently switching them to 400.
- `EmailExtractionPanel` treats every 422 as empty/oversized text and ignores
  validation headers. It does not yet call `require_complete=true`; that strict
  error path needs frontend coordination before adoption.
- The sample email has city/place names but no coordinates. The old prompt asked
  Gemini to approximate coordinates; that violates the no-fabrication requirement.
  The updated prompt flags these locations for manual completion. A verified
  geocoding or location-selection boundary needs a later coordinated change.
- The extraction panel has no editable manual form and parsing does not add a
  shipment to the fixtures or to scan input. Its suggestion to run a scan applies
  only to shipments already on file. A later write flow needs team agreement.
- The overview/proposals UI already calls scan, opportunity, proposal, decision,
  audit and reset endpoints. Those pre-existing routes remain available with
  their current behavior; Phase 1 adds no matching or workflow implementation.

## SQLite and Phase 2 boundary

Startup applies transactional migrations using `PRAGMA user_version`; version 1
creates empty `proposals`, `proposal_decisions`, `audit_events` and
`audit_visibility` tables. Initialization is idempotent, preserves rows and rejects
a database newer than this code supports. Foreign keys are enabled on the
migration connection; future repository connections must also enable them.

No proposal/decision/audit is written to these tables in Phase 1. Existing demo
stores remain in memory and reset keeps its existing behavior. Future repositories
must accept validated `Proposal`/`Decision`/`AuditEvent` schemas, enforce party and
visibility scope and atomic version checks, and serialize timezone-aware dates
and JSON snapshots. Keep creation/decision transactions together with audit writes.
Do not let the agent approve or dispatch. Matching/routing/impact/agent modules
remain teammate-owned and unchanged.

No deployment, commit, push or merge is part of this work. A real Gemini key,
live-provider verification and coordinated frontend manual completion remain
external follow-ups; mocked tests do not verify live Gemini behavior.
