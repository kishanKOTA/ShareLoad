import json
from pathlib import Path

import pytest

from app.matching import validate_candidate
from app.schemas import ReasonCode, Shipment, Trip, Vehicle

DEMO = Path(__file__).resolve().parents[3] / "data" / "demo"


def _load(name: str) -> list[dict]:
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def assumptions() -> dict:
    return json.loads((DEMO / "assumptions.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def trips() -> dict[str, Trip]:
    return {t["id"]: Trip(**t) for t in _load("trips.json")}


@pytest.fixture(scope="module")
def shipments() -> dict[str, Shipment]:
    return {s["id"]: Shipment(**s) for s in _load("shipments.json")}


@pytest.fixture(scope="module")
def vehicle() -> Vehicle:
    return Vehicle(**_load("vehicles.json")[0])


def _codes(result) -> set[ReasonCode]:
    return set(result.reason_codes)


def _check(result, name):
    return next(c for c in result.checks if c.name == name)


def test_demo_match_passes(trips, shipments, vehicle, assumptions):
    result = validate_candidate(trips["trip-a-return"], shipments["ship-b"], vehicle, assumptions)
    assert result.feasible, result.checks
    assert result.reason_codes == []
    assert all(c.passed for c in result.checks)


def test_reefer_load_rejected_for_temperature(trips, shipments, vehicle, assumptions):
    result = validate_candidate(trips["trip-a-return"], shipments["ship-b-reefer"], vehicle, assumptions)
    assert not result.feasible
    assert result.reason_codes == [ReasonCode.CARGO_TEMP_UNSUPPORTED]


def test_late_pickup_rejected_for_time_window(trips, shipments, vehicle, assumptions):
    result = validate_candidate(trips["trip-a-return"], shipments["ship-b-late"], vehicle, assumptions)
    assert _codes(result) == {ReasonCode.TIME_WINDOW_CONFLICT}
    assert not _check(result, "pickup_window").passed


def test_outbound_leg_has_no_room_and_wrong_direction(trips, shipments, vehicle, assumptions):
    result = validate_candidate(trips["trip-a-outbound"], shipments["ship-b"], vehicle, assumptions)
    assert {
        ReasonCode.CAPACITY_WEIGHT_EXCEEDED,
        ReasonCode.CAPACITY_VOLUME_EXCEEDED,
        ReasonCode.DIRECTION_MISMATCH,
    } <= _codes(result)


@pytest.mark.parametrize(
    ("weight", "volume", "expected"),
    [
        (4500, 30, set()),  # exactly at capacity is fine
        (4500.1, 30, {ReasonCode.CAPACITY_WEIGHT_EXCEEDED}),
        (4500, 30.1, {ReasonCode.CAPACITY_VOLUME_EXCEEDED}),
    ],
)
def test_capacity_edges(trips, shipments, vehicle, assumptions, weight, volume, expected):
    shipment = shipments["ship-b"].model_copy(update={"weight_kg": weight, "volume_m3": volume})
    result = validate_candidate(trips["trip-a-return"], shipment, vehicle, assumptions)
    assert _codes(result) == expected


def test_hazmat_rejected_on_dry_box(trips, shipments, vehicle, assumptions):
    shipment = shipments["ship-b"].model_copy(update={"hazardous": True})
    result = validate_candidate(trips["trip-a-return"], shipment, vehicle, assumptions)
    assert _codes(result) == {ReasonCode.HAZMAT_UNSUPPORTED}


def test_temperature_range_on_ambient_cargo_needs_reefer(trips, shipments, vehicle, assumptions):
    shipment = shipments["ship-b"].model_copy(update={"temp_min_c": 2, "temp_max_c": 8})
    result = validate_candidate(trips["trip-a-return"], shipment, vehicle, assumptions)
    assert _codes(result) == {ReasonCode.CARGO_TEMP_UNSUPPORTED}


def test_missing_fields_fail_dependent_checks(trips, vehicle, assumptions):
    shipment = Shipment(
        id="ship-x", org_id="lakeview", weight_kg=1200,
        extraction={"confidence": 0.6, "missing_fields": ["origin"]},
    )
    result = validate_candidate(trips["trip-a-return"], shipment, vehicle, assumptions)
    assert not result.feasible
    assert ReasonCode.MISSING_CRITICAL_FIELD in _codes(result)
    assert _check(result, "weight_capacity").passed
    for name in ("volume_capacity", "cargo_temperature", "hazmat", "direction",
                 "pickup_window", "delivery_window"):
        assert _check(result, name).reason_code is ReasonCode.MISSING_CRITICAL_FIELD


def test_delivery_window_too_early(trips, shipments, vehicle, assumptions):
    ship = shipments["ship-b"]
    early = ship.delivery_window.model_copy(
        update={"end": ship.delivery_window.start.replace(hour=13, minute=30)}
    )
    shipment = ship.model_copy(update={"delivery_window": early})
    result = validate_candidate(trips["trip-a-return"], shipment, vehicle, assumptions)
    assert _check(result, "pickup_window").passed
    assert _check(result, "delivery_window").reason_code is ReasonCode.TIME_WINDOW_CONFLICT


def test_uncached_route_cannot_confirm_time(trips, shipments, vehicle, assumptions):
    result = validate_candidate(
        trips["trip-a-return"], shipments["ship-b"], vehicle, assumptions,
        routes={"type": "FeatureCollection", "features": []},
    )
    assert _codes(result) == {ReasonCode.TIME_WINDOW_CONFLICT, ReasonCode.DETOUR_EXCEEDS_LIMIT}


def test_demo_detour_within_limit(trips, shipments, vehicle, assumptions):
    result = validate_candidate(trips["trip-a-return"], shipments["ship-b"], vehicle, assumptions)
    assert _check(result, "detour").detail == "6.1 km extra, limit 30 km"


@pytest.mark.parametrize(("limit", "passes"), [(6.1, True), (6.0, False)])
def test_detour_limit_edge(trips, shipments, vehicle, assumptions, limit, passes):
    tight = {**assumptions, "max_detour_km": {**assumptions["max_detour_km"], "value": limit}}
    result = validate_candidate(trips["trip-a-return"], shipments["ship-b"], vehicle, tight)
    assert _check(result, "detour").passed is passes
    assert _codes(result) == (set() if passes else {ReasonCode.DETOUR_EXCEEDS_LIMIT})


def test_mismatched_vehicle_raises(trips, shipments, vehicle, assumptions):
    other = vehicle.model_copy(update={"id": "veh-z"})
    with pytest.raises(ValueError):
        validate_candidate(trips["trip-a-return"], shipments["ship-b"], other, assumptions)
