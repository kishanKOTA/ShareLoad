"""Validated fixture snapshot, with ownership and reference integrity checks."""
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.schemas import Organization, Shipment, Trip, Vehicle


class FixtureError(ValueError):
    pass


@dataclass
class FixtureData:
    organizations: list[Organization]
    vehicles: list[Vehicle]
    trips: list[Trip]
    shipments: list[Shipment]


def load_fixtures(directory: Path) -> FixtureData:
    records = {}
    for name, schema in (("organizations", Organization), ("vehicles", Vehicle),
                         ("trips", Trip), ("shipments", Shipment)):
        try:
            records[name] = TypeAdapter(list[schema]).validate_python(
                json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise FixtureError(f"Invalid {name}.json fixture") from exc
        ids = [record.id for record in records[name]]
        if len(ids) != len(set(ids)):
            raise FixtureError(f"Duplicate IDs in {name}.json")
    org_ids = {o.id for o in records["organizations"]}
    for name in ("vehicles", "trips", "shipments"):
        if any(r.org_id not in org_ids for r in records[name]):
            raise FixtureError(f"Unknown organization in {name}.json")
    vehicles = {v.id: v for v in records["vehicles"]}
    for trip in records["trips"]:
        vehicle = vehicles.get(trip.vehicle_id)
        if vehicle is None or vehicle.org_id != trip.org_id:
            raise FixtureError("Trip vehicle must exist and belong to the trip organization")
    return FixtureData(**records)
