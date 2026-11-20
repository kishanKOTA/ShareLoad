"""Baseline vs shared route comparison from cached OSRM routes.

Routes live in ``data/demo/routes.geojson`` and are looked up by their exact
stop sequence (location names), so nothing here calls OSRM at runtime.

For a trip T (carrier A) and shipment S (shipper B), following docs/PRD.md:

- **Baseline** = A's round trip driven directly (the counterpart leg
  T.destination -> T.origin, plus T.origin -> T.destination) + B's hired truck
  S.origin -> S.destination -> S.origin.
- **Shared** = A's counterpart leg + T.origin -> S.origin -> S.destination ->
  T.destination. B's truck does not move.
- **Detour** = shared leg − direct leg, i.e. the extra km A drives for B.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import Field

from app.schemas import ContractModel, RouteScenario, Shipment, Trip

ROUTES_PATH = Path(__file__).resolve().parents[4] / "data" / "demo" / "routes.geojson"

Routes = Mapping[str, Any]
Feature = Mapping[str, Any]


class RouteNotCached(LookupError):
    """No cached route exists for a required stop sequence."""

    def __init__(self, stops: Sequence[str]):
        self.stops = list(stops)
        super().__init__(f"no cached route for {' -> '.join(stops)}")


class RouteComparison(ContractModel):
    trip_id: str
    shipment_id: str
    baseline: RouteScenario
    shared: RouteScenario
    detour_km: float = Field(ge=0)


@lru_cache(maxsize=1)
def load_routes() -> dict[str, Any]:
    with ROUTES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def find_route(stops: Sequence[str], routes: Routes | None = None) -> Feature | None:
    """The cached feature whose stops match ``stops`` exactly, or None."""
    wanted = list(stops)
    for feature in (routes or load_routes()).get("features", []):
        if feature.get("properties", {}).get("stops") == wanted:
            return feature
    return None


def require_route(stops: Sequence[str], routes: Routes | None = None) -> Feature:
    feature = find_route(stops, routes)
    if feature is None:
        raise RouteNotCached(stops)
    return feature


# Stop sequences --------------------------------------------------------------


def direct_stops(trip: Trip) -> list[str]:
    return [trip.origin.name, trip.destination.name]


def counterpart_stops(trip: Trip) -> list[str]:
    """The other leg of the carrier's round trip (outbound for a return, and vice versa)."""
    return [trip.destination.name, trip.origin.name]


def shared_stops(trip: Trip, shipment: Shipment) -> list[str]:
    if shipment.origin is None or shipment.destination is None:
        raise ValueError(f"shipment {shipment.id} has no origin/destination")
    return [trip.origin.name, shipment.origin.name, shipment.destination.name, trip.destination.name]


def shipper_baseline_stops(shipment: Shipment) -> list[str]:
    """B's hired truck: out to the customer and back empty."""
    if shipment.origin is None or shipment.destination is None:
        raise ValueError(f"shipment {shipment.id} has no origin/destination")
    return [shipment.origin.name, shipment.destination.name, shipment.origin.name]


# Derived values ---------------------------------------------------------------


def distance_km(feature: Feature) -> float:
    return float(feature["properties"]["distance_km"])


def leg_minutes(feature: Feature) -> list[float]:
    """Drive minutes per leg.

    The cache stores one duration per route, so it is split across legs in
    proportion to leg distance (stated simplification).
    """
    props = feature["properties"]
    legs_km = [float(km) for km in props["legs_km"]]
    total_km = sum(legs_km)
    if total_km <= 0:
        return [0.0 for _ in legs_km]
    per_km = float(props["duration_min"]) / total_km
    return [km * per_km for km in legs_km]


def detour_km(trip: Trip, shipment: Shipment, routes: Routes | None = None) -> float | None:
    """Extra km A drives to serve B, or None if the shared route isn't cached.

    The direct leg falls back to ``trip.distance_km`` (also OSRM) if its route
    isn't cached.
    """
    shared = find_route(shared_stops(trip, shipment), routes)
    if shared is None:
        return None
    direct = find_route(direct_stops(trip), routes)
    direct_km = distance_km(direct) if direct is not None else trip.distance_km
    return round(max(distance_km(shared) - direct_km, 0.0), 1)


def _collection(features: Sequence[Feature]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


def evaluate_routes(trip: Trip, shipment: Shipment, routes: Routes | None = None) -> RouteComparison:
    """Baseline and shared vehicle-km, detour and map geometry for one candidate.

    Raises ``RouteNotCached`` if any required route is missing from the cache.
    """
    counterpart = require_route(counterpart_stops(trip), routes)
    direct = require_route(direct_stops(trip), routes)
    shipper = require_route(shipper_baseline_stops(shipment), routes)
    shared_leg = require_route(shared_stops(trip, shipment), routes)

    detour = round(max(distance_km(shared_leg) - distance_km(direct), 0.0), 1)
    baseline = RouteScenario(
        description="A round trip + B hired round trip",
        distance_km=round(distance_km(counterpart) + distance_km(direct) + distance_km(shipper), 1),
        geometry=_collection([counterpart, direct, shipper]),
    )
    shared = RouteScenario(
        description="A round trip with B pickup and drop-off; B truck not used",
        distance_km=round(distance_km(counterpart) + distance_km(shared_leg), 1),
        detour_km=detour,
        geometry=_collection([counterpart, shared_leg]),
    )
    return RouteComparison(
        trip_id=trip.id, shipment_id=shipment.id, baseline=baseline, shared=shared, detour_km=detour
    )
