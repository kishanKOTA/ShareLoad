import json
from pathlib import Path

import pytest

from app.routing import RouteNotCached, detour_km, evaluate_routes
from app.schemas import Shipment, Trip

DEMO = Path(__file__).resolve().parents[3] / "data" / "demo"


def _load(name: str) -> list[dict]:
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def trip() -> Trip:
    return next(Trip(**t) for t in _load("trips.json") if t["id"] == "trip-a-return")


@pytest.fixture(scope="module")
def shipments() -> dict[str, Shipment]:
    return {s["id"]: Shipment(**s) for s in _load("shipments.json")}


def test_demo_comparison_matches_prd(trip, shipments):
    result = evaluate_routes(trip, shipments["ship-b"])
    assert result.baseline.distance_km == 944.0  # 236.4 + 240.5 + 467.1
    assert result.shared.distance_km == 483.0  # 236.4 + 246.6
    assert result.detour_km == result.shared.detour_km == 6.1
    assert result.baseline.detour_km == 0


def test_geometry_is_feature_collection_of_cached_routes(trip, shipments):
    result = evaluate_routes(trip, shipments["ship-b"])
    ids = lambda s: [f["properties"]["id"] for f in s.geometry["features"]]  # noqa: E731
    assert result.baseline.geometry["type"] == "FeatureCollection"
    assert ids(result.baseline) == ["route-a-outbound", "route-a-return-direct", "route-b-own-truck"]
    assert ids(result.shared) == ["route-a-outbound", "route-shared"]


def test_reefer_detour(trip, shipments):
    assert detour_km(trip, shipments["ship-b-reefer"]) == 11.4  # 251.9 − 240.5


def test_missing_baseline_route_raises(trip, shipments):
    # No cached hired-truck route to the grocery co-op.
    with pytest.raises(RouteNotCached):
        evaluate_routes(trip, shipments["ship-b-reefer"])


def test_uncached_detour_is_none(trip, shipments):
    assert detour_km(trip, shipments["ship-b"], {"features": []}) is None
