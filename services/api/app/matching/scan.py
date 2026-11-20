"""Scan the demo fixtures for trip/shipment sharing opportunities.

Every trip with spare capacity is paired with every shipment from another
organization. Each pair is validated; feasible pairs also get the baseline vs
shared routes and the impact numbers. Rejected pairs are kept with their
reason codes so the UI can show what was ruled out and why.

``score`` and ``explanation`` are left unset: ranking text is the agent's job.

Run ``python -m app.matching.scan`` from ``services/api`` to print a scan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field

from app.impact import calculate_impact
from app.routing import RouteNotCached, evaluate_routes, load_routes
from app.routing.routes import ROUTES_PATH
from app.schemas import ContractModel, Opportunity, Shipment, Trip, Vehicle

from .validator import validate_candidate

DEMO_DIR = ROUTES_PATH.parent


@dataclass(frozen=True)
class DemoData:
    trips: list[Trip]
    shipments: list[Shipment]
    vehicles: dict[str, Vehicle]
    assumptions: dict[str, Any]
    routes: dict[str, Any]


class ScanResult(ContractModel):
    candidates_considered: int = Field(ge=0)
    # Feasible, best net CO₂ saving first.
    opportunities: list[Opportunity] = Field(default_factory=list)
    rejected: list[Opportunity] = Field(default_factory=list)


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_demo_data(data_dir: Path = DEMO_DIR) -> DemoData:
    data_dir = Path(data_dir)
    routes = load_routes() if data_dir == DEMO_DIR else _read_json(data_dir / "routes.geojson")
    return DemoData(
        trips=[Trip(**t) for t in _read_json(data_dir / "trips.json")],
        shipments=[Shipment(**s) for s in _read_json(data_dir / "shipments.json")],
        vehicles={v["id"]: Vehicle(**v) for v in _read_json(data_dir / "vehicles.json")},
        assumptions=_read_json(data_dir / "assumptions.json"),
        routes=routes,
    )


def opportunity_id(trip: Trip, shipment: Shipment) -> str:
    return f"opp-{trip.id}-{shipment.id}"


def _has_spare_capacity(trip: Trip) -> bool:
    return trip.available_kg > 0 and trip.available_m3 > 0


def _evaluate(trip: Trip, shipment: Shipment, data: DemoData) -> Opportunity:
    vehicle = data.vehicles.get(trip.vehicle_id)
    if vehicle is None:
        raise ValueError(f"trip {trip.id} references unknown vehicle {trip.vehicle_id}")

    result = validate_candidate(trip, shipment, vehicle, data.assumptions, routes=data.routes)
    opportunity = Opportunity(
        id=opportunity_id(trip, shipment),
        trip_id=trip.id,
        shipment_id=shipment.id,
        feasible=result.feasible,
        reason_codes=result.reason_codes,
        checks=result.checks,
    )
    if not result.feasible:
        return opportunity

    try:
        comparison = evaluate_routes(trip, shipment, data.routes)
    except RouteNotCached:
        # Feasible, but a baseline route isn't cached; show it without impact numbers.
        return opportunity
    opportunity.baseline = comparison.baseline
    opportunity.shared = comparison.shared
    opportunity.impact = calculate_impact(
        comparison.baseline.distance_km, comparison.shared.distance_km, data.assumptions
    )
    return opportunity


def _net_co2(opportunity: Opportunity) -> float:
    return opportunity.impact.net_saved.co2_kg if opportunity.impact else float("-inf")


def scan_opportunities(data_dir: Path = DEMO_DIR) -> ScanResult:
    return _cached_scan(Path(data_dir)).model_copy(deep=True)


@lru_cache(maxsize=4)
def _cached_scan(data_dir: Path) -> ScanResult:
    data = load_demo_data(data_dir)
    candidates = [
        (trip, shipment)
        for trip in data.trips
        if _has_spare_capacity(trip)
        for shipment in data.shipments
        if shipment.org_id != trip.org_id
    ]
    evaluated = [_evaluate(trip, shipment, data) for trip, shipment in candidates]
    return ScanResult(
        candidates_considered=len(candidates),
        opportunities=sorted((o for o in evaluated if o.feasible), key=_net_co2, reverse=True),
        rejected=[o for o in evaluated if not o.feasible],
    )


def clear_scan_cache() -> None:
    """Forget cached scans, e.g. after a demo reset or fixture change."""
    _cached_scan.cache_clear()


def get_opportunity(opportunity_id: str, data_dir: Path = DEMO_DIR) -> Opportunity | None:
    """One scanned candidate (feasible or rejected) by id, or None."""
    scan = _cached_scan(Path(data_dir))
    for opportunity in (*scan.opportunities, *scan.rejected):
        if opportunity.id == opportunity_id:
            return opportunity.model_copy(deep=True)
    return None


def _print_scan(scan: ScanResult) -> None:
    print(f"Candidates considered: {scan.candidates_considered}\n")
    for o in scan.opportunities:
        print(f"FEASIBLE  {o.id}")
        if o.impact:
            net, pct = o.impact.net_saved, o.impact.reduction_pct
            print(
                f"          baseline {o.baseline.distance_km} km -> shared {o.shared.distance_km} km "
                f"(detour {o.shared.detour_km} km)"
            )
            print(
                f"          saves {net.distance_km} km ({pct}%), {net.fuel_l} L, "
                f"{net.co2_kg} kg CO2, ${net.cost_usd:.2f}"
            )
    for o in scan.rejected:
        print(f"REJECTED  {o.id}: {', '.join(c.value for c in o.reason_codes)}")
        for check in o.checks:
            if not check.passed:
                print(f"          - {check.name}: {check.detail}")


if __name__ == "__main__":
    _print_scan(scan_opportunities())
