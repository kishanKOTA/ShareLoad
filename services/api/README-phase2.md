# Phase 2 backend platform

This extends Phase 1 with actual engine integration, SQLite proposals and dual
approval, scoped audit, guarded reset, and deployment configuration. No matching,
routing, impact, agent, frontend, schema or source-fixture code is changed.
All demo organizations and business records are fictional sample data.

## Run locally

From the repository root, use Python 3.11+ (verified on 3.11.17):

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r services/api/requirements.txt
# Copy only when .env does not already exist; keep existing secrets private.
cp -n .env.example .env
SHARELOAD_ENV=demo SHARELOAD_DEMO_MODE=true SHARELOAD_USE_GEMINI=false \
  uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000 --workers 1
```

This runs real deterministic matching, routing and impact functions and their
engine template explanations, with Gemini disabled. To use live Gemini, set the
key privately, enable `SHARELOAD_USE_GEMINI=true`, and restart. A returned
`mode=template` or `cached=true` is not proof of a live Gemini invocation.

Start the unchanged frontend from `apps/web` with `npm ci` then
`NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev`. No frontend source
change is required for the existing scan/proposal/decision/reset requests.

Run the suite from `services/api`:

```bash
../../.venv/bin/python -m pytest -q
```

## Endpoints and contracts

All business endpoints are under `/api/v1`.

| Endpoint | Behavior |
| --- | --- |
| `POST /opportunities/scan?use_cached=false` | Calls Kishan's `run_agent_scan`; preserves engine reason codes, geometry, metrics, formula traces and guarded explanations |
| `GET /opportunities/{id}` | Calls Kishan's deterministic `get_opportunity`; reuses the persisted agent explanation only if all underlying evidence still matches |
| `POST /opportunities/{id}/proposals` | 201 direct Proposal, status `pending_approvals`, immutable full Opportunity snapshot |
| `POST /proposals/{id}/decision` | Body `{decision, comment}`; direct updated Proposal |
| `GET /proposals` | Direct array for participating organizations only |
| `GET /audit-events` | Direct array, oldest first, explicit organization visibility |
| `POST /demo/reset` | Demo guard required; returns `{"status":"reset"}` |
| `GET /health`, `/api/v1/health` | Liveness, `{"status":"ok"}` |
| `GET /ready`, `/api/v1/ready` | SQLite access/schema readiness, `{"status":"ready"}` |

Organizations and Phase 1 read/extraction endpoints remain available. OpenAPI is
at `/docs`. Dates carry ISO-8601 offsets; units remain km, kg, m3 and litres.

Opportunity and workflow requests require a known `X-Org-Id`. This header is a
**demo workspace selector, not production authentication**. Missing context gives
422, blank gives 400, unknown/nonparty gives 403, unknown entity gives 404,
duplicate/closed/stale-reset conflicts give 409. Invalid bodies/comments give
422. Comments are limited to the frontend's 500 characters. Database availability
errors give 503 with `Retry-After: 1`; engine failures give a safe 502 detail.
Error `detail` strings work with the existing client; FastAPI body validation
retains its standard field-error array.

A proposal requires two distinct participants, feasibility, passed checks, route
geometry, impact and formula evidence. No feasibility or arithmetic is added by
the API. Negative engine results are preserved, never forced green. One active or
approved proposal may exist per opportunity; a rejected opportunity proposal can
be proposed anew under a new ID. Duplicate POSTs return 409; no additional state
or audit event is written. A party decides once. One approval produces
`partially_approved`; two produce `approved_for_external_coordination`; either
party's rejection closes it as `rejected`. Final proposals cannot change.
Only user decision HTTP requests can approve: no agent tool is wired to approval,
and actor/org overrides in the decision body are rejected.

## Persistence, privacy and reset

SQLite migration 2 extends the Phase 1 schema with a partial unique index,
immutable snapshot/party trigger, audit visibility index and persistent scan/reset
generation state. Each request uses a fresh connection with foreign keys enabled.
`BEGIN IMMEDIATE` serializes workflow writers across app instances, including
concurrent decisions. Proposal/decision writes and their audit entries share the
same transaction; audit failure rolls the workflow back. IDs use UUIDs and are
never reset/reused. Schema migration runs transactionally at startup; back up
existing SQLite files before deployment. Newer unsupported schema versions fail
startup. There is no automatic destructive downgrade.

Only the two participating organizations see a proposal, snapshot or decision
comments. Scan events include relevant tool calls within `scan.completed.payload`;
no raw emails or provider exception text is recorded. Each organization receives
its own scoped event. The response also filters candidates and tool calls by
participation. A global summary is suppressed as an empty string when some
candidates are outside that org's visibility, rather than synthesizing a new AI
explanation. The locked two-org demo retains the complete original summary.

The engine works on a fingerprinted copy under `SHARELOAD_RUNTIME_DIR`, not on
`data/demo`. Live Gemini cache writes go there. Linux file locking serializes
engine/cache operations across processes sharing that runtime directory. A
shared SQLite last-scan record preserves explanations across restarts; evidence
comparison prevents stale explanations being applied to changed engine results.
Runtime inputs are fixed for a running deployment; restart after approved fixture
changes. Deploy one service instance/worker on a local persistent volume; this is
not a distributed database or a network-filesystem deployment.

Reset is disabled by default. It requires `SHARELOAD_DEMO_MODE=true` and a
non-production environment. Configuration fails if production and demo reset are
both enabled. The existing UI sends reset without an org header; this remains an
explicit demo-wide operation. Anyone able to reach an enabled demo can reset it.
Reset atomically clears proposals, decisions, visibility entries and prior audit
rows, clears persisted last-scan state, increments the reset generation and logs
one `demo.reset` event visible to known demo organizations. It restores writable
inputs and the committed seeded agent cache, clears deterministic scan caches,
and leaves source fixtures untouched. Seeded workflow state is zero proposals and
zero decisions, with that one reset event. File caches are disposable; SQLite
workflow/reset writes are atomic. No history-retention guarantee is implied by a
demo reset. A stale create crossing reset fails 409; stale proposal IDs fail 404.

## Environment reference

Process environment overrides root `.env`. Paths resolve from repository root.
Restart after changing settings; never commit `.env` or real keys.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SHARELOAD_ENV` | `development` | `development`, `test`, `demo`, `production` |
| `SHARELOAD_DEMO_MODE` | `false` | Enables reset only outside production |
| `SHARELOAD_USE_GEMINI` | `true` | `false` forces deterministic/template operation |
| `SHARELOAD_DATABASE_PATH` | `services/api/shareload.db` | Persistent SQLite file |
| `SHARELOAD_RUNTIME_DIR` | DB parent + `/runtime` | Writable fixture/cache copy; `.env.example` sets `services/api/runtime` |
| `SHARELOAD_DATA_DIR` | `data/demo` | Read-only source fixtures |
| `CORS_ORIGINS` | localhost and 127.0.0.1 port 3000 | Exact comma-separated frontend origins, no wildcard/trailing slash |
| `GEMINI_API_KEY` | empty | Server-side Gemini key; absent key permits engine templates and extraction 503 |
| `GEMINI_MODEL` | `gemini-flash-latest` | Provider model; pin privately for reproducibility |
| `GEMINI_TIMEOUT_MS` | `30000` | Timeout per Gemini HTTP request; not an overall scan deadline |
| `PORT` | hosting platform provided | Used by deployment start command |
| `PYTHON_VERSION` | Render config: `3.11.17` | Hosting interpreter selection |

The platform's provider client is passed to the unchanged agent, so scan and
extraction use the configured timeout. The agent may make multiple sequential
requests; configure proxy/client deadlines accordingly. An unconfigured or failed
Gemini scan uses the existing engine's templates; cached mode replays the existing
fingerprinted cache. No fixture-only fake opportunities are introduced.

## Frontend integration notes for Stephanie

- Existing direct arrays, Proposal snapshots, party ordering (carrier, shipper),
  statuses, decisions and `scan.completed` payload shape are preserved. CORS
  allows GET/POST, Content-Type and X-Org-Id only for configured origins.
- Opportunity APIs now require `X-Org-Id`; the current pages already send it.
- Reset confirmation currently says all audit events are deleted. The backend
  retains a single reset event for accountability; its default timeline rendering
  works, but a friendly label for `demo.reset` would improve the UI.
- The PRD mentions assumptions and a shared-fields preview in Opportunity detail;
  the frozen Python/TypeScript Opportunity schema has no separate fields for
  either. Geometry, formula traces and assumptions version are preserved. The UI
  currently displays methodology text/trace; coordinate a schema revision if the
  full assumptions document or a sharing preview is wanted.
- Phase 1 extraction is still read-only, has no editable manual form, and lacks
  geocoding when emails omit coordinates. A scan uses seeded shipments, not a new
  parsed email. Do not claim the extracted shipment was saved or matched.
- On a partial scope, `agent_summary` can be empty. The locked two-org demo is
  unaffected. Optional future UI copy can explain that the list is scoped.
- Build frontend with `NEXT_PUBLIC_API_URL=https://<backend>/api/v1`, and configure
  backend CORS with its exact HTTPS frontend origin. This is public sample-data
  context, not production tenant authentication; real data requires auth work.

## Deployment steps (prepared, not deployed)

`render.yaml` describes a single native Python web service, explicit persistent
volume, `/ready` health check and manual deploys. It follows Render's
[Blueprint fields](https://render.com/docs/blueprint-spec) and
[health checks](https://render.com/docs/health-checks). No Docker or frontend
hosting changes are introduced.

1. Review the backend diff and run the suite. Back up any existing SQLite DB.
2. When team-approved source is available to hosting, create a Render Blueprint
   using repository-root `render.yaml`; keep repository root as build context.
3. Supply the exact frontend `CORS_ORIGINS` and server Gemini key in the host's
   secret settings (or run with no key/templates). Keep DB and runtime directory
   on `/var/data`. This blueprint requests a service plan with a persistent disk;
   review hosting charges before provisioning.
4. Default config is `production` with reset disabled. For the fictional demo,
   explicitly change BOTH `SHARELOAD_ENV=demo` and `SHARELOAD_DEMO_MODE=true`.
5. Build: `pip install -r services/api/requirements.txt`. Start:
   `uvicorn app.main:app --app-dir services/api --host 0.0.0.0 --port $PORT --workers 1`.
   Migrations run at startup; health route is `/ready`.
6. Set frontend API URL at its build time, redeploy it, verify allowed-origin
   preflight and follow the manual demo procedure below.
7. Restart the backend after a partial approval and verify the snapshot, decision,
   audit and version persist before taking the final approval. Disable demo reset
   again when it is no longer needed.

This task does not provision hosting, push source, migrate a remote database,
or verify a live deployment.

## Exact manual demo verification

Use only the fictional seeded demo and explicitly enable reset. In a second
terminal, run from repository root against the local server started above:

```bash
.venv/bin/python services/api/scripts/verify_demo.py \
  --base-url http://127.0.0.1:8000 --reset
```

The script performs actual HTTP requests, restores the seed, reads org-scoped
records, checks cross-org denial, scans the real engine, checks both reason codes
and detail geometry/trace, proposes, checks a duplicate, approves as NorthStar,
checks a duplicate decision, approves as Lakeview, checks both orgs' lists and
audit, resets, rejects a new proposal, checks the final-state conflict, and resets
to the seed again. It prints scan mode/cache status and fails on any mismatch.
It records user approvals only as part of this explicit manual test.

Then verify the unchanged browser UI:

1. Open `http://localhost:3000`; confirm Sample data and both orgs in the switcher.
2. As NorthStar, reset; uncheck cached result; run scan. With Gemini disabled,
   confirm Template, one feasible and two rejected cards with the locked reasons.
3. Open the match. Inspect baseline/shared routes, every feasibility check,
   impact and methodology formula trace. They must match the API engine results.
4. Create a proposal. Open Proposals, approve as NorthStar with a comment and
   verify `partially_approved`; Lakeview remains undecided.
5. Refresh and restart the backend with the same database path. Confirm that
   proposal, comment, snapshot and audit remain. Switch to Lakeview and approve.
6. Confirm `approved_for_external_coordination`, both decision cards and audit.
   Refresh both org views; the final proposal cannot be decided again.
7. Reset; create again; reject as either org. Verify rejected and no further
   decision action. Reset again; proposal list is empty, audit has one reset event.
8. Separately start with reset disabled and confirm `POST /api/v1/demo/reset`
   returns 403. Confirm `/health`, `/ready` and configured-origin preflight.

For live Gemini verification, privately set a real key, enable Gemini, restart,
uncheck cached scan and inspect `mode=gemini`, `cached=false` and actual tool
calls. Extraction also needs a real provider request and human field review.
Neither mocks, cached runs nor template results verify live provider behavior.
The browser, live-provider and deployed checks must be recorded separately from
the local HTTP/template and automated test results.

## AI usage disclosure

In product: Gemini extracts shipment fields and drives the existing agent's tool
calls/explanations. Deterministic Python owns feasibility and every arithmetic
result; engine guardrails replace unsupported numbers with templates. The API
adds persistence, scoping and human decisions, never automatic AI approval or
dispatch. Cached OSRM fixtures are used, without live routing or fleet integration.

Development: OpenAI Codex assisted with Phase 1 and Phase 2 platform implementation,
SQLite integration, tests, deployment configuration and documentation in this
session. Preserve the repository's existing disclosures; teammates must add any
other assistants they used before submission. Do not infer a full team tool list
from this session.

## Verification record for this implementation

- Full backend suite: 186 passed on Python 3.11.17; affected opportunity/workflow
  tests were rechecked (42 passed) after the final fallback-status wording change.
  The installed Starlette/httpx combination emits a deprecation warning.
- Actual local Uvicorn + HTTP verification script: passed, `mode=template`,
  `cached=false`; no live Gemini request was made.
- Unchanged Next.js dev frontend in a browser: organization loading, scan cards,
  opportunity routes/checks/impact, proposal creation, NorthStar partial approval,
  Lakeview final approval and scoped audit were verified. The real API was then
  restarted; HTTP verified the final proposal and both decisions persisted.
- Verified source fixtures, frozen schemas, PRD and matching/routing/impact/agent/
  frontend source files were unchanged. Deployment YAML parses locally.
- Live Gemini, a hosted deploy, production authentication and the Phase 1 manual
  extraction UI/geocoding gaps remain unverified or outside this phase.
