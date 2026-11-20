import pytest
from pydantic import ValidationError

from app.schemas import (
    CargoType,
    Check,
    Opportunity,
    ReasonCode,
    Shipment,
    TimeWindow,
    Trip,
    Vehicle,
)

CHICAGO = {"name": "Chicago, IL", "lat": 41.8781, "lon": -87.6298}
MADISON = {"name": "Madison, WI", "lat": 43.0731, "lon": -89.4012}


def window(start: str, end: str) -> dict:
    return {"start": f"2026-11-24T{start}:00-06:00", "end": f"2026-11-24T{end}:00-06:00"}


def test_demo_vehicle_and_return_trip_validate():
    vehicle = Vehicle(
        id="veh-a", org_id="northstar", type="box_truck", payload_kg=4500,
        volume_m3=30, capabilities=["ambient"], fuel_l_per_100km=26,
    )
    assert vehicle.can_carry(CargoType.AMBIENT)
    assert not vehicle.can_carry(CargoType.REFRIGERATED)

    trip = Trip(
        id="trip-a-return", org_id="northstar", vehicle_id="veh-a",
        origin=CHICAGO, destination=MADISON,
        depart_window=window("11:00", "14:00"), arrive_window=window("14:00", "18:00"),
        distance_km=240, available_kg=4500, available_m3=30, leg="return",
    )
    assert trip.leg.value == "return"


def test_demo_shipment_validates_with_no_missing_fields():
    shipment = Shipment(
        id="ship-b", org_id="lakeview", origin=CHICAGO, destination=MADISON,
        weight_kg=1200, volume_m3=8, cargo_type="ambient", hazardous=False,
        pickup_window=window("08:00", "12:00"), delivery_window=window("13:00", "20:00"),
    )
    assert shipment.missing_critical_fields() == []


def test_partial_extraction_reports_missing_fields():
    shipment = Shipment(
        id="ship-x", org_id="lakeview", raw_text="Need 1200 kg moved to Madison",
        weight_kg=1200, extraction={"confidence": 0.6, "missing_fields": ["origin"]},
    )
    assert "origin" in shipment.missing_critical_fields()


def test_naive_datetimes_rejected():
    with pytest.raises(ValidationError):
        TimeWindow(start="2026-11-24T08:00:00", end="2026-11-24T12:00:00")


def test_reversed_window_rejected():
    with pytest.raises(ValidationError):
        TimeWindow(**window("12:00", "08:00"))


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Vehicle(
            id="v", org_id="o", type="t", payload_kg=1, volume_m3=1,
            fuel_l_per_100km=1, colour="red",
        )


def test_failed_check_requires_reason_code():
    with pytest.raises(ValidationError):
        Check(name="temperature", passed=False)


def test_opportunity_feasibility_must_match_reason_codes():
    rejected = Opportunity(
        id="opp-2", trip_id="t", shipment_id="s", feasible=False,
        reason_codes=[ReasonCode.CARGO_TEMP_UNSUPPORTED],
    )
    assert rejected.model_dump(mode="json")["reason_codes"] == ["CARGO_TEMP_UNSUPPORTED"]

    with pytest.raises(ValidationError):
        Opportunity(id="o", trip_id="t", shipment_id="s", feasible=False)
    with pytest.raises(ValidationError):
        Opportunity(
            id="o", trip_id="t", shipment_id="s", feasible=True,
            reason_codes=[ReasonCode.DETOUR_EXCEEDS_LIMIT],
        )
