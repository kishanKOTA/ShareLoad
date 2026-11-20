"""Constraint validator for one trip/shipment candidate.

``validate_candidate`` runs every check and reports all failures, not just the
first, so the Opportunity detail page can show the whole checklist. Each check
either passes or fails with exactly one ``ReasonCode``; a check whose input is
missing from the shipment fails with ``MISSING_CRITICAL_FIELD``.

Timing uses cached OSRM routes from ``data/demo/routes.geojson``. A shared route
is looked up by its stop sequence:

    trip origin -> shipment origin -> shipment destination -> trip destination

The cache stores one ``duration_min`` per route plus per-leg distances, so each
leg's drive time is the route duration split in proportion to leg distance
(stated simplification). Loading/unloading dwell time is not modelled.

The detour (shared leg − direct leg) must not exceed ``max_detour_km`` from
assumptions. A candidate whose shared route isn't cached fails the time and
detour checks, since neither can be confirmed.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from pydantic import Field

from app.routing import routes as routing
from app.schemas import (
    CargoType,
    Check,
    ContractModel,
    Location,
    ReasonCode,
    Shipment,
    TimeWindow,
    Trip,
    Vehicle,
)

# Largest allowed angle between the trip's and the shipment's compass bearings.
# Can be overridden with an optional "max_bearing_diff_deg" entry in assumptions.
DEFAULT_MAX_BEARING_DIFF_DEG = 45.0

TEMP_CONTROLLED = (CargoType.REFRIGERATED, CargoType.FROZEN)


class ValidationResult(ContractModel):
    feasible: bool
    checks: list[Check] = Field(default_factory=list)
    reason_codes: list[ReasonCode] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def validate_candidate(
    trip: Trip,
    shipment: Shipment,
    vehicle: Vehicle,
    assumptions: Mapping[str, Any],
    routes: Mapping[str, Any] | None = None,
) -> ValidationResult:
    """Check whether ``shipment`` can ride on ``trip`` using ``vehicle``.

    ``routes`` is a GeoJSON FeatureCollection; it defaults to the cached demo
    routes and is only a parameter so tests can inject their own.
    """
    if vehicle.id != trip.vehicle_id:
        raise ValueError(f"vehicle {vehicle.id} does not run trip {trip.id} ({trip.vehicle_id})")
    if routes is None:
        routes = routing.load_routes()

    missing = _missing_fields(shipment)
    checks = [
        _check_critical_fields(missing),
        _check_weight(trip, shipment, vehicle),
        _check_volume(trip, shipment, vehicle),
        _check_cargo_temperature(shipment, vehicle),
        _check_hazmat(shipment, vehicle),
        _check_direction(trip, shipment, _max_bearing_diff(assumptions)),
        _check_detour(trip, shipment, routes, _max_detour_km(assumptions)),
        *_check_time_windows(trip, shipment, routes),
    ]

    reason_codes: list[ReasonCode] = []
    for check in checks:
        if check.reason_code is not None and check.reason_code not in reason_codes:
            reason_codes.append(check.reason_code)

    return ValidationResult(feasible=not reason_codes, checks=checks, reason_codes=reason_codes)


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #


def _missing_fields(shipment: Shipment) -> list[str]:
    """Unset critical fields plus anything extraction flagged, in stable order."""
    flagged = shipment.extraction.missing_fields if shipment.extraction else []
    return list(dict.fromkeys([*shipment.missing_critical_fields(), *flagged]))


def _passed(name: str, detail: str) -> Check:
    return Check(name=name, passed=True, detail=detail)


def _failed(name: str, code: ReasonCode, detail: str) -> Check:
    return Check(name=name, passed=False, reason_code=code, detail=detail)


def _missing(name: str, fields: Iterable[str]) -> Check:
    return _failed(
        name,
        ReasonCode.MISSING_CRITICAL_FIELD,
        f"cannot check: shipment is missing {', '.join(fields)}",
    )


def _check_critical_fields(missing: list[str]) -> Check:
    name = "critical_fields"
    if missing:
        return _failed(name, ReasonCode.MISSING_CRITICAL_FIELD, f"missing: {', '.join(missing)}")
    return _passed(name, "all critical fields present")


def _check_weight(trip: Trip, shipment: Shipment, vehicle: Vehicle) -> Check:
    name = "weight_capacity"
    if shipment.weight_kg is None:
        return _missing(name, ["weight_kg"])
    available = min(trip.available_kg, vehicle.payload_kg)
    detail = f"{shipment.weight_kg:,.0f} kg needed, {available:,.0f} kg available"
    if shipment.weight_kg > available:
        return _failed(name, ReasonCode.CAPACITY_WEIGHT_EXCEEDED, detail)
    return _passed(name, detail)


def _check_volume(trip: Trip, shipment: Shipment, vehicle: Vehicle) -> Check:
    name = "volume_capacity"
    if shipment.volume_m3 is None:
        return _missing(name, ["volume_m3"])
    available = min(trip.available_m3, vehicle.volume_m3)
    detail = f"{shipment.volume_m3:,.1f} m³ needed, {available:,.1f} m³ available"
    if shipment.volume_m3 > available:
        return _failed(name, ReasonCode.CAPACITY_VOLUME_EXCEEDED, detail)
    return _passed(name, detail)


def _required_cargo_type(shipment: Shipment) -> CargoType:
    """Capability the vehicle needs, tightened by any stated temperature range."""
    cargo = shipment.cargo_type
    assert cargo is not None
    if shipment.temp_max_c is not None and shipment.temp_max_c <= 0:
        return CargoType.FROZEN
    if cargo not in TEMP_CONTROLLED and (
        shipment.temp_min_c is not None or shipment.temp_max_c is not None
    ):
        # A stated temperature range can't be guaranteed by an unchilled box.
        return CargoType.REFRIGERATED
    return cargo


def _check_cargo_temperature(shipment: Shipment, vehicle: Vehicle) -> Check:
    name = "cargo_temperature"
    if shipment.cargo_type is None:
        return _missing(name, ["cargo_type"])
    if shipment.cargo_type is CargoType.HAZARDOUS:
        return _passed(name, "hazardous cargo is covered by the hazmat check")

    required = _required_cargo_type(shipment)
    capabilities = ", ".join(c.value for c in vehicle.capabilities) or "none"
    temp = _format_temp_range(shipment)
    detail = f"needs {required.value}{temp}; vehicle carries {capabilities}"
    if not vehicle.can_carry(required):
        return _failed(name, ReasonCode.CARGO_TEMP_UNSUPPORTED, detail)
    return _passed(name, detail)


def _format_temp_range(shipment: Shipment) -> str:
    lo, hi = shipment.temp_min_c, shipment.temp_max_c
    if lo is None and hi is None:
        return ""
    if lo is not None and hi is not None:
        return f" ({lo:g} to {hi:g} °C)"
    return f" (min {lo:g} °C)" if lo is not None else f" (max {hi:g} °C)"


def _check_hazmat(shipment: Shipment, vehicle: Vehicle) -> Check:
    name = "hazmat"
    is_hazardous = shipment.hazardous or shipment.cargo_type is CargoType.HAZARDOUS
    if shipment.hazardous is None and not is_hazardous:
        return _missing(name, ["hazardous"])
    if not is_hazardous:
        return _passed(name, "not hazardous")
    if not vehicle.can_carry(CargoType.HAZARDOUS):
        return _failed(name, ReasonCode.HAZMAT_UNSUPPORTED, "hazardous load; vehicle is not hazmat-rated")
    return _passed(name, "hazardous load; vehicle is hazmat-rated")


def _max_bearing_diff(assumptions: Mapping[str, Any]) -> float:
    entry = assumptions.get("max_bearing_diff_deg")
    if entry is None:
        return DEFAULT_MAX_BEARING_DIFF_DEG
    return float(entry["value"] if isinstance(entry, Mapping) else entry)


def _bearing_deg(a: Location, b: Location) -> float:
    """Initial great-circle bearing from a to b, 0-360 degrees clockwise from north."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlon = math.radians(b.lon - a.lon)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def _check_direction(trip: Trip, shipment: Shipment, max_diff_deg: float) -> Check:
    name = "direction"
    missing = [f for f in ("origin", "destination") if getattr(shipment, f) is None]
    if missing:
        return _missing(name, missing)
    trip_bearing = _bearing_deg(trip.origin, trip.destination)
    ship_bearing = _bearing_deg(shipment.origin, shipment.destination)
    diff = abs((trip_bearing - ship_bearing + 180) % 360 - 180)
    detail = (
        f"trip heads {trip_bearing:.0f}°, shipment heads {ship_bearing:.0f}° "
        f"({diff:.0f}° apart, limit {max_diff_deg:g}°)"
    )
    if diff > max_diff_deg:
        return _failed(name, ReasonCode.DIRECTION_MISMATCH, detail)
    return _passed(name, detail)


def _max_detour_km(assumptions: Mapping[str, Any]) -> float:
    entry = assumptions["max_detour_km"]
    return float(entry["value"] if isinstance(entry, Mapping) else entry)


def _no_route_detail(trip: Trip, shipment: Shipment) -> str:
    return (
        f"no cached route for {' -> '.join(routing.shared_stops(trip, shipment))}; "
        "cannot confirm"
    )


def _check_detour(
    trip: Trip, shipment: Shipment, routes: Mapping[str, Any], max_km: float
) -> Check:
    name = "detour"
    missing = [f for f in ("origin", "destination") if getattr(shipment, f) is None]
    if missing:
        return _missing(name, missing)
    detour = routing.detour_km(trip, shipment, routes)
    if detour is None:
        return _failed(name, ReasonCode.DETOUR_EXCEEDS_LIMIT, _no_route_detail(trip, shipment))
    detail = f"{detour:,.1f} km extra, limit {max_km:g} km"
    if detour > max_km:
        return _failed(name, ReasonCode.DETOUR_EXCEEDS_LIMIT, detail)
    return _passed(name, detail)


# --------------------------------------------------------------------------- #
# Time windows
# --------------------------------------------------------------------------- #


def _shared_leg_minutes(
    trip: Trip, shipment: Shipment, routes: Mapping[str, Any]
) -> tuple[float, float] | None:
    """Drive minutes (trip origin -> pickup, pickup -> delivery), or None if not cached."""
    feature = routing.find_route(routing.shared_stops(trip, shipment), routes)
    if feature is None:
        return None
    legs = routing.leg_minutes(feature)
    return legs[0], legs[1]


def _clip(lo: datetime, hi: datetime, window: TimeWindow, offset: timedelta) -> tuple[datetime, datetime]:
    """Narrow departure range [lo, hi] so that departure + offset lands inside window."""
    return max(lo, window.start - offset), min(hi, window.end - offset)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _check_time_windows(trip: Trip, shipment: Shipment, routes: Mapping[str, Any]) -> list[Check]:
    """Is there a departure inside the trip's depart window that makes both windows?

    Waiting at the pickup is modelled as departing later, so it is bounded by
    the end of the trip's depart window.
    """
    pickup_name, delivery_name = "pickup_window", "delivery_window"
    needed = ("origin", "destination", "pickup_window", "delivery_window")
    missing = [f for f in needed if getattr(shipment, f) is None]
    if missing:
        return [_missing(pickup_name, missing), _missing(delivery_name, missing)]

    legs = _shared_leg_minutes(trip, shipment, routes)
    if legs is None:
        detail = _no_route_detail(trip, shipment)
        return [
            _failed(pickup_name, ReasonCode.TIME_WINDOW_CONFLICT, detail),
            _failed(delivery_name, ReasonCode.TIME_WINDOW_CONFLICT, detail),
        ]

    to_pickup = timedelta(minutes=legs[0])
    to_delivery = to_pickup + timedelta(minutes=legs[1])
    depart = trip.depart_window
    pw, dw = shipment.pickup_window, shipment.delivery_window
    assert pw is not None and dw is not None

    # Pickup: departures that reach the pickup inside its window.
    p_lo, p_hi = _clip(depart.start, depart.end, pw, to_pickup)
    pickup_ok = p_lo <= p_hi
    if pickup_ok:
        pickup = _passed(
            pickup_name,
            f"arrive {_fmt(p_lo + to_pickup)}–{_fmt(p_hi + to_pickup)} "
            f"({legs[0]:.0f} min drive), window {_fmt(pw.start)}–{_fmt(pw.end)}",
        )
    else:
        pickup = _failed(
            pickup_name,
            ReasonCode.TIME_WINDOW_CONFLICT,
            f"truck can arrive {_fmt(depart.start + to_pickup)}–{_fmt(depart.end + to_pickup)} "
            f"({legs[0]:.0f} min drive), window {_fmt(pw.start)}–{_fmt(pw.end)}",
        )

    # Delivery: among pickup-feasible departures (or all, if pickup already failed).
    base_lo, base_hi = (p_lo, p_hi) if pickup_ok else (depart.start, depart.end)
    d_lo, d_hi = _clip(base_lo, base_hi, dw, to_delivery)
    leg_note = f"{legs[1]:.0f} min from pickup"
    if d_lo <= d_hi:
        delivery = _passed(
            delivery_name,
            f"arrive {_fmt(d_lo + to_delivery)}–{_fmt(d_hi + to_delivery)} "
            f"({leg_note}), window {_fmt(dw.start)}–{_fmt(dw.end)}",
        )
    else:
        delivery = _failed(
            delivery_name,
            ReasonCode.TIME_WINDOW_CONFLICT,
            f"truck can arrive {_fmt(base_lo + to_delivery)}–{_fmt(base_hi + to_delivery)} "
            f"({leg_note}), window {_fmt(dw.start)}–{_fmt(dw.end)}",
        )
    return [pickup, delivery]
