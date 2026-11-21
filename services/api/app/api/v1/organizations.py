"""Organization-scoped sample data. X-Org-Id is demo context, not authentication."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.v1.fixtures import FixtureData, load_fixtures
from app.schemas import Organization, Shipment, Trip, Vehicle

router = APIRouter(prefix="/api/v1")


def fixture_data(request: Request) -> FixtureData:
    # Startup stores a validated snapshot; lazy loading also supports TestClient
    # callers that do not enter the lifespan context.
    if request.app.state.fixtures is None:
        request.app.state.fixtures = load_fixtures(request.app.state.data_dir)
    return request.app.state.fixtures


def authorized_org(
    org_id: str,
    data: Annotated[FixtureData, Depends(fixture_data)],
    x_org_id: Annotated[str, Header()],
) -> str:
    if org_id not in {o.id for o in data.organizations}:
        raise HTTPException(404, f"Organization {org_id!r} not found")
    if not x_org_id.strip():
        raise HTTPException(400, "X-Org-Id must not be blank")
    if x_org_id.strip() != org_id:
        raise HTTPException(403, "X-Org-Id does not match this organization")
    return org_id


@router.get("/organizations", response_model=list[Organization])
def organizations(data: Annotated[FixtureData, Depends(fixture_data)]):
    return data.organizations


@router.get("/organizations/{org_id}/vehicles", response_model=list[Vehicle])
def vehicles(org_id: Annotated[str, Depends(authorized_org)],
             data: Annotated[FixtureData, Depends(fixture_data)]):
    return [v for v in data.vehicles if v.org_id == org_id]


@router.get("/organizations/{org_id}/trips", response_model=list[Trip])
def trips(org_id: Annotated[str, Depends(authorized_org)],
          data: Annotated[FixtureData, Depends(fixture_data)]):
    return [t for t in data.trips if t.org_id == org_id]


@router.get("/organizations/{org_id}/shipments", response_model=list[Shipment])
def shipments(org_id: Annotated[str, Depends(authorized_org)],
              data: Annotated[FixtureData, Depends(fixture_data)]):
    return [s for s in data.shipments if s.org_id == org_id]
