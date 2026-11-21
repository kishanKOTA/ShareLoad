"""ShareLoad platform API.

Phase 1 adds validated demo reads, extraction and SQLite startup infrastructure.
Pre-existing scan/proposal/audit/reset routes are retained for compatibility;
their workflows and persistence are outside this change. X-Org-Id is sample
workspace context only, never production authentication. See README-phase1.md.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_config
from app.api.v1.fixtures import FixtureError, load_fixtures
from app.api.v1.organizations import router as organization_router
from app.models.database import initialize_database

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

DECISION_EVENTS = {
    DecisionType.APPROVE: "proposal.approved",
    DecisionType.REJECT: "proposal.rejected",
}


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


def _find_opportunity(request: Request, opportunity_id: str) -> Opportunity | None:
    last: AgentScanResult | None = request.app.state.last_scan
    if last is not None:
        for o in (*last.opportunities, *last.rejected):
            if o.id == opportunity_id:
                return o.model_copy(deep=True)
    return get_opportunity(opportunity_id, request.app.state.data_dir)


def _parties(data_dir: Path, opportunity: Opportunity) -> list[str]:
    """[trip owner, shipment owner] for an opportunity."""
    data = load_demo_data(data_dir)
    trip = next(t for t in data.trips if t.id == opportunity.trip_id)
    shipment = next(s for s in data.shipments if s.id == opportunity.shipment_id)
    return [trip.org_id, shipment.org_id]


router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/opportunities/scan", response_model=AgentScanResult)
def scan(request: Request, use_cached: bool = False) -> AgentScanResult:
    state = request.app.state
    result = run_agent_scan(
        data_dir=state.data_dir, use_gemini=state.use_gemini, use_cached=use_cached
    )
    state.last_scan = result
    state.audit.record(
        actor=Actor.AGENT,
        event_type="scan.completed",
        entity="scan",
        payload={
            "mode": result.mode,
            "cached": result.cached,
            "candidates_considered": result.candidates_considered,
            "opportunity_ids": [o.id for o in result.opportunities],
            "rejected_ids": [o.id for o in result.rejected],
            "tool_calls": result.tool_calls,
        },
    )
    return result


@router.get("/opportunities/{opportunity_id}", response_model=Opportunity)
def read_opportunity(opportunity_id: str, request: Request) -> Opportunity:
    opportunity = _find_opportunity(request, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id!r} not found")
    return opportunity


@router.post("/opportunities/{opportunity_id}/proposals", response_model=Proposal, status_code=201)
def create_proposal(
    opportunity_id: str,
    request: Request,
    org_id: Annotated[str, Depends(_current_org)],
) -> Proposal:
    state = request.app.state
    opportunity = _find_opportunity(request, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id!r} not found")
    parties = _parties(state.data_dir, opportunity)
    try:
        proposal = state.proposals.create(opportunity, parties, created_by=org_id)
    except ProposalForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ProposalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    state.audit.record(
        actor=Actor.USER,
        org_id=org_id,
        event_type="proposal.created",
        entity=f"proposal:{proposal.id}",
        payload={"opportunity_id": opportunity_id, "status": proposal.status.value},
        visible_to=proposal.parties,
    )
    return proposal


@router.post("/proposals/{proposal_id}/decision", response_model=Proposal)
def decide_proposal(
    proposal_id: str,
    body: DecisionRequest,
    request: Request,
    org_id: Annotated[str, Depends(_current_org)],
) -> Proposal:
    state = request.app.state
    try:
        proposal = state.proposals.decide(proposal_id, org_id, body.decision, body.comment)
    except ProposalNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found") from exc
    except ProposalForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ProposalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    state.audit.record(
        actor=Actor.USER,
        org_id=org_id,
        event_type=DECISION_EVENTS[body.decision],
        entity=f"proposal:{proposal.id}",
        payload={
            "decision": body.decision.value,
            "comment": body.comment,
            "status": proposal.status.value,
            "version": proposal.version,
        },
        visible_to=proposal.parties,
    )
    return proposal


@router.get("/proposals", response_model=list[Proposal])
def list_proposals(request: Request, org_id: Annotated[str, Depends(_current_org)]) -> list[Proposal]:
    return request.app.state.proposals.list_for(org_id)


@router.get("/audit-events", response_model=list[AuditEvent])
def list_audit_events(
    request: Request, org_id: Annotated[str, Depends(_current_org)]
) -> list[AuditEvent]:
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


@router.post("/demo/reset")
def reset_demo(request: Request) -> dict[str, str]:
    state = request.app.state
    state.proposals.clear()
    state.audit.clear()
    state.last_scan = None
    clear_scan_cache()
    return {"status": "reset"}


def create_app(data_dir: Path | None = None, use_gemini: bool = True,
               database_path: Path | None = None) -> FastAPI:
    """Build the API; fixture validation and SQLite initialization run at startup."""
    settings = get_config()
    selected_data_dir = Path(data_dir) if data_dir is not None else settings.data_dir
    selected_database = Path(database_path) if database_path is not None else settings.database_path

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.fixtures = load_fixtures(selected_data_dir)
        initialize_database(selected_database)
        yield

    application = FastAPI(title="ShareLoad API", version="1.0.0", lifespan=lifespan)
    application.state.data_dir = selected_data_dir
    application.state.database_path = selected_database
    application.state.fixtures = None
    application.state.use_gemini = use_gemini
    # Pre-existing demo behavior. Phase 1 does not migrate or extend these stores.
    application.state.last_scan = None
    application.state.proposals = ProposalStore()
    application.state.audit = AuditLog()

    @application.exception_handler(FixtureError)
    async def fixture_error(request: Request, exc: FixtureError):
        return JSONResponse(status_code=500, content={
            "detail": "Demo fixtures are invalid. Contact the API operator.",
            "code": "FIXTURE_VALIDATION_ERROR",
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
    application.include_router(organization_router)
    application.include_router(router)
    return application


app = create_app()
