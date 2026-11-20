"""HTTP API for the ShareLoad demo, mounted under ``/api/v1``.

Run from ``services/api``::

    uvicorn app.main:app --reload

Org-scoped routes (``/organizations/{id}/trips`` and ``/shipments``) need an
``X-Org-Id`` header naming the caller's organization. An organization can read
only its own trips and shipments: a header that doesn't match the path id gets
403, and a missing header gets 422 (FastAPI's standard missing-header error).

``POST /opportunities/scan`` runs the agent scan; ``?use_cached=true`` returns
the last saved Gemini run when the data hasn't changed. ``GET
/opportunities/{id}`` serves the opportunity from the most recent scan (so it
carries the agent's explanation), or from the deterministic scan if no scan has
been run yet.

Proposals and the audit log live in memory on ``app.state`` (see
``app.proposals`` and ``app.audit``). Every proposal route takes ``X-Org-Id``:
an org sees only proposals it is a party to and the audit events visible to it.
``POST /ingest/shipments/parse`` (``X-Org-Id`` required) has Gemini turn free
text into a Shipment for the caller's org; it returns 503 when no Gemini key is
configured and 502 when Gemini fails or returns bad JSON twice.

``POST /demo/reset`` clears proposals, audit events and the in-memory scan
caches. It keeps ``last_agent_scan.json``, so ``use_cached`` still works after
a reset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agent.agent import AgentScanResult, run_agent_scan
from app.agent.config import get_gemini_client
from app.audit import AuditLog
from app.ingestion import (
    ExtractionFailed,
    ExtractionUnavailable,
    ParseShipmentRequest,
    extract_shipment,
)
from app.matching.scan import DEMO_DIR, clear_scan_cache, get_opportunity, load_demo_data
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
    Trip,
)

CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

DECISION_EVENTS = {
    DecisionType.APPROVE: "proposal.approved",
    DecisionType.REJECT: "proposal.rejected",
}


def _data_dir(request: Request) -> Path:
    return request.app.state.data_dir


def _load_organizations(data_dir: Path) -> list[Organization]:
    with open(Path(data_dir) / "organizations.json", encoding="utf-8") as f:
        return [Organization(**o) for o in json.load(f)]


def _authorized_org(
    org_id: str,
    data_dir: Annotated[Path, Depends(_data_dir)],
    x_org_id: Annotated[str, Header()],
) -> str:
    """The path org, after checking it exists and matches the caller's X-Org-Id."""
    if org_id not in {o.id for o in _load_organizations(data_dir)}:
        raise HTTPException(status_code=404, detail=f"Organization {org_id!r} not found")
    if x_org_id.strip() != org_id:
        raise HTTPException(status_code=403, detail="X-Org-Id does not match this organization")
    return org_id


def _current_org(
    data_dir: Annotated[Path, Depends(_data_dir)],
    x_org_id: Annotated[str, Header()],
) -> str:
    """The caller's org from X-Org-Id; 403 if it isn't a known organization."""
    org_id = x_org_id.strip()
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


@router.get("/organizations", response_model=list[Organization])
def list_organizations(data_dir: Annotated[Path, Depends(_data_dir)]) -> list[Organization]:
    return _load_organizations(data_dir)


@router.get("/organizations/{org_id}/trips", response_model=list[Trip])
def list_trips(
    org_id: Annotated[str, Depends(_authorized_org)],
    data_dir: Annotated[Path, Depends(_data_dir)],
) -> list[Trip]:
    return [t for t in load_demo_data(data_dir).trips if t.org_id == org_id]


@router.get("/organizations/{org_id}/shipments", response_model=list[Shipment])
def list_shipments(
    org_id: Annotated[str, Depends(_authorized_org)],
    data_dir: Annotated[Path, Depends(_data_dir)],
) -> list[Shipment]:
    return [s for s in load_demo_data(data_dir).shipments if s.org_id == org_id]


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


@router.post("/ingest/shipments/parse", response_model=Shipment)
def parse_shipment(
    body: ParseShipmentRequest,
    request: Request,
    org_id: Annotated[str, Depends(_current_org)],
) -> Shipment:
    """Gemini extracts a Shipment for the caller's org from free text. Not saved."""
    client = get_gemini_client() if request.app.state.use_gemini else None
    try:
        return extract_shipment(body.raw_text, org_id, client)
    except ExtractionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Shipment extraction is unavailable: GEMINI_API_KEY is not set. "
            "Enter the shipment fields manually.",
        ) from exc
    except ExtractionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/demo/reset")
def reset_demo(request: Request) -> dict[str, str]:
    state = request.app.state
    state.proposals.clear()
    state.audit.clear()
    state.last_scan = None
    clear_scan_cache()
    return {"status": "reset"}


def create_app(data_dir: Path = DEMO_DIR, use_gemini: bool = True) -> FastAPI:
    """Build the app. Tests pass a temp ``data_dir`` and ``use_gemini=False``."""
    application = FastAPI(title="ShareLoad API", version="1.0.0")
    application.state.data_dir = Path(data_dir)
    application.state.use_gemini = use_gemini
    application.state.last_scan = None
    application.state.proposals = ProposalStore()
    application.state.audit = AuditLog()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


app = create_app()
