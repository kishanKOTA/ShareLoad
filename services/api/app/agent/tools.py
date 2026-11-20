"""Tools the agent can call, as thin wrappers over the deterministic engine.

Each tool takes plain string ids, returns a JSON-safe dict, and never raises for
bad input: an unknown id or uncached route comes back as ``{"error": ...}`` so
the model can recover. Every call is appended to ``tool_calls`` as
``{"name", "args", "ok", "summary"}`` for the scan response and audit trail.

The tools live on an ``AgentTools`` instance rather than at module level so each
scan gets its own call log (no shared global state between API requests). The
bound methods are ordinary callables with typed signatures, so they can be
handed straight to Gemini function calling via ``as_functions()``.

``evaluate_routes`` leaves out map geometry: it's large and the model doesn't
need it. The UI gets geometry from ``get_opportunity()``.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from app.impact import calculate_impact as _calculate_impact
from app.matching.scan import DemoData, candidate_pairs, load_demo_data
from app.matching.validator import validate_candidate as _validate_candidate
from app.routing import RouteNotCached
from app.routing import evaluate_routes as _evaluate_routes
from app.schemas import Shipment, Trip, Vehicle

log = logging.getLogger(__name__)

ToolResult = dict[str, Any]


class ToolError(Exception):
    """Bad tool input; reported to the model as an error result."""


def _tool(summarize: Callable[[ToolResult], str]):
    """Run the tool, turn ToolError into an error result, and log the call."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self: "AgentTools", *args: Any, **kwargs: Any) -> ToolResult:
            call_args = dict(zip(fn.__code__.co_varnames[1:], args)) | kwargs
            try:
                result = fn(self, *args, **kwargs)
                ok, summary = True, summarize(result)
            except ToolError as exc:
                result = {"error": str(exc)}
                ok, summary = False, f"error: {exc}"
            self.tool_calls.append(
                {"name": fn.__name__, "args": call_args, "ok": ok, "summary": summary}
            )
            log.info("tool %s(%s) -> %s", fn.__name__, call_args, summary)
            return result

        return wrapper

    return decorator


def _summarize_candidates(r: ToolResult) -> str:
    return f"{r['count']} candidate pair(s)"


def _summarize_validation(r: ToolResult) -> str:
    if r["feasible"]:
        return f"feasible ({len(r['checks'])} checks passed)"
    return "infeasible: " + ", ".join(r["reason_codes"])


def _summarize_routes(r: ToolResult) -> str:
    return (
        f"baseline {r['baseline_km']} km, shared {r['shared_km']} km, "
        f"detour {r['detour_km']} km"
    )


def _summarize_impact(r: ToolResult) -> str:
    net = r["net_saved"]
    return f"saves {net['distance_km']} km ({r['reduction_pct']}%), {net['co2_kg']} kg CO2"


class AgentTools:
    def __init__(self, data: DemoData | None = None):
        self.data = data or load_demo_data()
        self.tool_calls: list[dict[str, Any]] = []

    def as_functions(self) -> list[Callable[..., ToolResult]]:
        """The tools, ready to pass to Gemini function calling."""
        return [self.list_candidates, self.validate_candidate, self.evaluate_routes, self.calculate_impact]

    # Lookups -----------------------------------------------------------------

    def _trip(self, trip_id: str) -> Trip:
        for trip in self.data.trips:
            if trip.id == trip_id:
                return trip
        raise ToolError(f"unknown trip_id {trip_id!r}")

    def _shipment(self, shipment_id: str) -> Shipment:
        for shipment in self.data.shipments:
            if shipment.id == shipment_id:
                return shipment
        raise ToolError(f"unknown shipment_id {shipment_id!r}")

    def _vehicle(self, trip: Trip) -> Vehicle:
        vehicle = self.data.vehicles.get(trip.vehicle_id)
        if vehicle is None:
            raise ToolError(f"trip {trip.id} references unknown vehicle {trip.vehicle_id}")
        return vehicle

    def _routes(self, trip_id: str, shipment_id: str):
        trip, shipment = self._trip(trip_id), self._shipment(shipment_id)
        try:
            return _evaluate_routes(trip, shipment, self.data.routes)
        except RouteNotCached as exc:
            raise ToolError(str(exc)) from exc
        except ValueError as exc:  # shipment missing origin/destination
            raise ToolError(str(exc)) from exc

    # Tools -------------------------------------------------------------------

    @_tool(_summarize_candidates)
    def list_candidates(self) -> ToolResult:
        """List trip/shipment pairs worth checking: trips with spare capacity
        paired with shipments from other organizations."""
        pairs = [
            {
                "trip_id": trip.id,
                "shipment_id": shipment.id,
                "trip_org_id": trip.org_id,
                "shipment_org_id": shipment.org_id,
                "trip_route": f"{trip.origin.name} -> {trip.destination.name}",
                "shipment_route": (
                    f"{shipment.origin.name} -> {shipment.destination.name}"
                    if shipment.origin and shipment.destination
                    else None
                ),
            }
            for trip, shipment in candidate_pairs(self.data)
        ]
        return {"count": len(pairs), "candidates": pairs}

    @_tool(_summarize_validation)
    def validate_candidate(self, trip_id: str, shipment_id: str) -> ToolResult:
        """Check capacity, cargo, hazmat, direction, detour and time windows for
        one trip/shipment pair. Returns feasible, reason_codes and every check."""
        trip, shipment = self._trip(trip_id), self._shipment(shipment_id)
        result = _validate_candidate(
            trip, shipment, self._vehicle(trip), self.data.assumptions, routes=self.data.routes
        )
        return {"trip_id": trip_id, "shipment_id": shipment_id, **result.model_dump(mode="json")}

    @_tool(_summarize_routes)
    def evaluate_routes(self, trip_id: str, shipment_id: str) -> ToolResult:
        """Compare total vehicle-km without sharing (baseline) and with sharing,
        plus the carrier's detour, from cached OSRM routes."""
        c = self._routes(trip_id, shipment_id)
        return {
            "trip_id": trip_id,
            "shipment_id": shipment_id,
            "baseline_km": c.baseline.distance_km,
            "baseline_description": c.baseline.description,
            "shared_km": c.shared.distance_km,
            "shared_description": c.shared.description,
            "detour_km": c.detour_km,
        }

    @_tool(_summarize_impact)
    def calculate_impact(self, trip_id: str, shipment_id: str) -> ToolResult:
        """Fuel, cost and CO2 for baseline vs shared, with net savings and the
        formula trace. A negative saving means not recommended."""
        c = self._routes(trip_id, shipment_id)
        impact = _calculate_impact(c.baseline.distance_km, c.shared.distance_km, self.data.assumptions)
        return {"trip_id": trip_id, "shipment_id": shipment_id, **impact.model_dump(mode="json")}
