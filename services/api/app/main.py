"""ShareLoad platform API.

Phase 2 integrates the engine with transactional SQLite proposals and audit.
X-Org-Id is sample workspace context, never production authentication.
See README-phase2.md for deployment and frontend contracts.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_config
from app.api.v1.fixtures import FixtureError, load_fixtures
from app.api.v1.organizations import router as organization_router
from app.models.database import Database
from app.api.v1.engine import EngineWorkspace, parties_for, scoped_scan

from app.agent.agent import AgentScanResult, run_agent_scan
from app.ingestion.provider import get_gemini_client
from app.audit import AuditLog
from app.ingestion import (
    ExtractionFailed,
    ExtractionUnavailable,
    ParseShipmentRequest,
    extract_shipment,
)
from app.matching.scan import clear_scan_cache, get_opportunity, load_demo_data
from app.proposals import ProposalConflict, ProposalForbidden, ProposalNotFound, ProposalStore
from app.schemas import (
    Actor,
    AuditEvent,
    DecisionRequest,
    DecisionType,
    Opportunity,
    Organization,
    Proposal,
    Shipment,
)

def _data_dir(request: Request) -> Path:
    return request.app.state.data_dir


def _load_organizations(data_dir: Path) -> list[Organization]:
    return load_fixtures(data_dir).organizations


def _current_org(
    data_dir: Annotated[Path, Depends(_data_dir)],
    x_org_id: Annotated[str, Header()],
) -> str:
    """The caller's org from X-Org-Id; 403 if it isn't a known organization."""
    org_id = x_org_id.strip()
    if not org_id:
        raise HTTPException(status_code=400, detail="X-Org-Id must not be blank")
    if org_id not in {o.id for o in _load_organizations(data_dir)}:
        raise HTTPException(status_code=403, detail=f"Unknown organization {org_id!r}")
    return org_id


def _generation(request: Request) -> int:
    with request.app.state.database.transaction() as connection:
        return connection.execute("SELECT generation FROM runtime_state WHERE id=1").fetchone()[0]


def _find_opportunity(request: Request, opportunity_id: str) -> Opportunity | None:
    state = request.app.state
    # Always resolve the deterministic engine record first; a prior scan may only
    # supply an explanation when the underlying evidence is identical.
    with state.engine.locked() as directory:
        try:
            opportunity = get_opportunity(opportunity_id, directory)
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(502, "Opportunity engine data is unavailable. Contact the API operator.") from exc
    if opportunity is None:
        return None
    with state.database.transaction() as connection:
        stored = connection.execute("SELECT last_scan_json FROM runtime_state WHERE id=1").fetchone()[0]
    if stored:
        last = AgentScanResult.model_validate_json(stored)
        for previous in (*last.opportunities, *last.rejected):
            if previous.id == opportunity_id and previous.model_dump(exclude={"explanation"}) == opportunity.model_dump(exclude={"explanation"}):
                return previous
    return opportunity


def _parties(data_dir: Path, opportunity: Opportunity) -> list[str]:
    return parties_for(opportunity, load_fixtures(data_dir))


router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/opportunities/scan", response_model=AgentScanResult)
def scan(request: Request, org_id: Annotated[str, Depends(_current_org)],
         use_cached: bool = False) -> AgentScanResult:
    state = request.app.state
    with state.engine.locked() as directory:
        generation = _generation(request)
        client = None
        try:
            client = get_gemini_client() if state.use_gemini else None
            result = run_agent_scan(data_dir=directory, use_gemini=client is not None,
                                    use_cached=use_cached, **({"client": client} if client else {}))
        except Exception as exc:
            raise HTTPException(502, "Opportunity engine failed. Retry or use the cached demo scan.") from exc
        finally:
            if client is not None and callable(getattr(client, "close", None)):
                try:
                    client.close()
                except Exception:
                    pass
        if result.fallback_reason:
            result.fallback_reason = (
                "Gemini disabled" if not state.use_gemini else
                "Gemini unavailable; engine templates used"
            )
        data = load_fixtures(state.data_dir)
        with state.database.transaction(write=True) as connection:
            if connection.execute("SELECT generation FROM runtime_state WHERE id=1").fetchone()[0] != generation:
                raise HTTPException(409, "Demo was reset; run a new scan")
            connection.execute("UPDATE runtime_state SET last_scan_json=? WHERE id=1", (result.model_dump_json(),))
            for org in data.organizations:
                visible = scoped_scan(result, org.id, data)
                if not visible.candidates_considered:
                    continue
                state.audit.record(connection=connection, actor=Actor.AGENT,
                    event_type="scan.completed", entity="scan", visible_to=[org.id],
                    payload={"mode": visible.mode, "cached": visible.cached,
                             "candidates_considered": visible.candidates_considered,
                             "opportunity_ids": [o.id for o in visible.opportunities],
                             "rejected_ids": [o.id for o in visible.rejected],
                             "tool_calls": visible.tool_calls})
        return scoped_scan(result, org_id, data)


@router.get("/opportunities/{opportunity_id}", response_model=Opportunity)
def read_opportunity(opportunity_id: str, request: Request,
                     org_id: Annotated[str, Depends(_current_org)]) -> Opportunity:
    opportunity = _find_opportunity(request, opportunity_id)
    if opportunity is None:
        raise HTTPException(404, f"Opportunity {opportunity_id!r} not found")
    if org_id not in _parties(request.app.state.data_dir, opportunity):
        raise HTTPException(403, "Only the trip and shipment owner can view this opportunity")
    return opportunity


@router.post("/opportunities/{opportunity_id}/proposals", response_model=Proposal, status_code=201)
def create_proposal(opportunity_id: str, request: Request,
                    org_id: Annotated[str, Depends(_current_org)]) -> Proposal:
    generation = _generation(request)
    opportunity = _find_opportunity(request, opportunity_id)
    if opportunity is None:
        raise HTTPException(404, f"Opportunity {opportunity_id!r} not found")
    parties = _parties(request.app.state.data_dir, opportunity)
    try:
        return request.app.state.proposals.create(opportunity, parties, created_by=org_id,
                                                 generation=generation)
    except ProposalForbidden as exc:
        raise HTTPException(403, str(exc)) from exc
    except ProposalConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/proposals/{proposal_id}/decision", response_model=Proposal)
def decide_proposal(proposal_id: str, body: DecisionRequest, request: Request,
                    org_id: Annotated[str, Depends(_current_org)]) -> Proposal:
    if body.comment is not None and len(body.comment) > 500:
        raise HTTPException(422, "Decision comment must be at most 500 characters")
    try:
        return request.app.state.proposals.decide(proposal_id, org_id, body.decision, body.comment)
    except ProposalNotFound as exc:
        raise HTTPException(404, f"Proposal {proposal_id!r} not found") from exc
    except ProposalForbidden as exc:
        raise HTTPException(403, str(exc)) from exc
    except ProposalConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/proposals", response_model=list[Proposal])
def list_proposals(request: Request, org_id: Annotated[str, Depends(_current_org)]) -> list[Proposal]:
    return request.app.state.proposals.list_for(org_id)


@router.get("/audit-events", response_model=list[AuditEvent])
def list_audit_events(request: Request, org_id: Annotated[str, Depends(_current_org)]) -> list[AuditEvent]:
    return request.app.state.audit.list_for(org_id)


@router.post(
    "/ingest/shipments/parse", response_model=Shipment,
    responses={
        422: {"description": "Invalid request, or missing fields when require_complete=true"},
        502: {"description": "Gemini failed; manual entry required"},
        503: {"description": "Gemini not configured; manual entry required"},
    },
)
def parse_shipment(
    body: ParseShipmentRequest,
    request: Request,
    response: Response,
    org_id: Annotated[str, Depends(_current_org)],
    require_complete: bool = False,
) -> Shipment:
    """Gemini extracts a Shipment for the caller's org from free text. Not saved."""
    client = None
    try:
        client = get_gemini_client() if request.app.state.use_gemini else None
        shipment = extract_shipment(body.raw_text, org_id, client)
        missing = shipment.extraction.missing_fields
        if missing:
            errors = [{"field": field, "code": "MISSING_CRITICAL_FIELD"} for field in missing]
            if require_complete:
                return JSONResponse(status_code=422, content={
                    "detail": "Missing critical shipment fields; enter them manually.",
                    "code": "MISSING_CRITICAL_FIELD", "missing_fields": missing,
                    "errors": errors, "shipment": shipment.model_dump(mode="json"),
                })
            response.headers["X-Shipment-Validation-Errors"] = json.dumps(errors)
            response.headers["X-Manual-Entry-Required"] = "true"
        return shipment
    except ExtractionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Shipment extraction is unavailable: GEMINI_API_KEY is not set. "
            "Enter the shipment fields manually.",
        ) from exc
    except ExtractionFailed as exc:
        # Provider exceptions can include request URLs, raw text or credentials.
        detail = ("Gemini returned invalid shipment JSON after 2 attempts. "
                  if exc.kind == "invalid_output" else "Gemini request failed. ")
        if exc.kind == "quota":
            detail = "Gemini quota exceeded. "
        raise HTTPException(status_code=502, detail=detail + "Enter shipment fields manually.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Gemini request failed. Enter shipment fields manually.") from exc
    finally:
        if client is not None and callable(getattr(client, "close", None)):
            try:
                client.close()
            except Exception:
                pass  # Cleanup must not replace an extraction result or safe API error.


@router.get("/ready")
def ready(request: Request) -> dict[str, str]:
    with request.app.state.database.transaction() as connection:
        connection.execute("SELECT generation FROM runtime_state WHERE id=1").fetchone()
    return {"status": "ready"}


@router.post("/demo/reset")
def reset_demo(request: Request) -> dict[str, str]:
    state = request.app.state
    if not state.demo_mode or state.environment == "production":
        raise HTTPException(403, "Demo reset is disabled; explicitly enable SHARELOAD_DEMO_MODE outside production")
    data = load_fixtures(state.data_dir)
    with state.engine.locked():
        state.engine.reset_cache()
        with state.database.transaction(write=True) as connection:
            for table in ("proposal_decisions", "proposals", "audit_visibility", "audit_events"):
                connection.execute(f"DELETE FROM {table}")
            connection.execute("UPDATE runtime_state SET generation=generation+1, last_scan_json=NULL WHERE id=1")
            state.audit.record(connection=connection, actor=Actor.USER, event_type="demo.reset", entity="demo",
                               visible_to=[o.id for o in data.organizations],
                               payload={"seed": "fixtures", "proposals": 0})
        clear_scan_cache()
    return {"status": "reset"}


def create_app(data_dir: Path | None = None, use_gemini: bool | None = None,
               database_path: Path | None = None, demo_mode: bool | None = None,
               runtime_dir: Path | None = None) -> FastAPI:
    """Build the API; fixture validation and SQLite initialization run at startup."""
    settings = get_config()
    selected_data_dir = Path(data_dir) if data_dir is not None else settings.data_dir
    selected_database = Path(database_path) if database_path is not None else settings.database_path

    selected_runtime = Path(runtime_dir) if runtime_dir is not None else (
        selected_database.parent / "runtime" if database_path is not None else settings.runtime_dir)
    database = Database(selected_database)
    engine = EngineWorkspace(selected_data_dir, selected_runtime)
    selected_demo_mode = settings.demo_mode if demo_mode is None else demo_mode
    if selected_demo_mode and settings.environment == "production":
        raise ValueError("Demo reset cannot be enabled in production")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.fixtures = load_fixtures(selected_data_dir)
        database.initialize()
        with engine.locked():
            pass
        yield

    application = FastAPI(title="ShareLoad API", version="1.0.0", lifespan=lifespan)
    application.state.data_dir = selected_data_dir
    application.state.database_path = selected_database
    application.state.fixtures = None
    application.state.use_gemini = settings.use_gemini if use_gemini is None else use_gemini
    application.state.database = database
    application.state.engine = engine
    application.state.demo_mode = selected_demo_mode
    application.state.environment = settings.environment
    application.state.audit = AuditLog(database)
    application.state.proposals = ProposalStore(database, application.state.audit)

    @application.exception_handler(FixtureError)
    async def fixture_error(request: Request, exc: FixtureError):
        return JSONResponse(status_code=500, content={
            "detail": "Demo fixtures are invalid. Contact the API operator.",
            "code": "FIXTURE_VALIDATION_ERROR",
        })

    @application.exception_handler(sqlite3.OperationalError)
    async def database_error(request: Request, exc: sqlite3.OperationalError):
        return JSONResponse(status_code=503, headers={"Retry-After": "1"}, content={
            "detail": "Database is temporarily unavailable; reload state before retrying.",
            "code": "DATABASE_UNAVAILABLE",
        })

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type", "X-Org-Id"],
        expose_headers=["X-Shipment-Validation-Errors", "X-Manual-Entry-Required"],
    )
    application.add_api_route("/health", health, methods=["GET"])
    application.add_api_route("/ready", ready, methods=["GET"])
    application.include_router(organization_router)
    application.include_router(router)
    return application


app = create_app()
