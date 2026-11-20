import inspect
import json

import pytest

from app.agent.tools import AgentTools


@pytest.fixture
def tools():
    return AgentTools()


def test_list_candidates(tools):
    result = tools.list_candidates()
    assert result["count"] == 3
    assert {c["shipment_id"] for c in result["candidates"]} == {"ship-b", "ship-b-reefer", "ship-b-late"}
    assert all(c["trip_id"] == "trip-a-return" for c in result["candidates"])


def test_validate_candidate_feasible_and_rejected(tools):
    ok = tools.validate_candidate("trip-a-return", "ship-b")
    assert ok["feasible"] and ok["reason_codes"] == []

    reefer = tools.validate_candidate("trip-a-return", "ship-b-reefer")
    assert reefer["reason_codes"] == ["CARGO_TEMP_UNSUPPORTED"]

    late = tools.validate_candidate("trip-a-return", shipment_id="ship-b-late")
    assert late["reason_codes"] == ["TIME_WINDOW_CONFLICT"]


def test_evaluate_routes_has_no_geometry(tools):
    result = tools.evaluate_routes("trip-a-return", "ship-b")
    assert result["baseline_km"] == 944.0
    assert result["shared_km"] == 483.0
    assert result["detour_km"] == 6.1
    assert "geometry" not in json.dumps(result)


def test_calculate_impact_matches_prd(tools):
    result = tools.calculate_impact("trip-a-return", "ship-b")
    assert result["net_saved"]["co2_kg"] == 323.6
    assert result["net_saved"]["fuel_l"] == 119.9
    assert result["recommended"] is True
    assert result["formula_trace"]


def test_results_are_json_safe(tools):
    for result in (
        tools.list_candidates(),
        tools.validate_candidate("trip-a-return", "ship-b"),
        tools.evaluate_routes("trip-a-return", "ship-b"),
        tools.calculate_impact("trip-a-return", "ship-b"),
    ):
        assert json.loads(json.dumps(result)) == result


def test_bad_ids_return_errors_and_are_logged(tools):
    assert tools.validate_candidate("nope", "ship-b") == {"error": "unknown trip_id 'nope'"}
    assert "error" in tools.calculate_impact("trip-a-return", "nope")
    assert [c["ok"] for c in tools.tool_calls] == [False, False]


def test_every_call_is_logged(tools):
    tools.list_candidates()
    tools.validate_candidate("trip-a-return", "ship-b-reefer")
    tools.evaluate_routes("trip-a-return", shipment_id="ship-b")
    tools.calculate_impact("trip-a-return", "ship-b")

    assert [c["name"] for c in tools.tool_calls] == [
        "list_candidates", "validate_candidate", "evaluate_routes", "calculate_impact",
    ]
    assert tools.tool_calls[1] == {
        "name": "validate_candidate",
        "args": {"trip_id": "trip-a-return", "shipment_id": "ship-b-reefer"},
        "ok": True,
        "summary": "infeasible: CARGO_TEMP_UNSUPPORTED",
    }
    assert tools.tool_calls[2]["args"] == {"trip_id": "trip-a-return", "shipment_id": "ship-b"}
    assert tools.tool_calls[3]["summary"] == "saves 461.0 km (48.8%), 323.6 kg CO2"


def test_call_logs_are_per_instance():
    a, b = AgentTools(), AgentTools()
    a.list_candidates()
    assert len(a.tool_calls) == 1 and b.tool_calls == []


def test_signatures_visible_for_function_calling(tools):
    # Gemini builds the tool schema from the signature and docstring.
    sig = inspect.signature(tools.validate_candidate)
    assert list(sig.parameters) == ["trip_id", "shipment_id"]
    assert tools.validate_candidate.__doc__
    assert len(tools.as_functions()) == 4
