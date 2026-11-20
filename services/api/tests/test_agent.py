"""Agent scan tests. Gemini is replaced by a fake client; no network calls."""

import json
from types import SimpleNamespace

import pytest

from app.agent import agent as agent_mod
from app.agent.agent import run_agent_scan

MATCH = "opp-trip-a-return-ship-b"
REEFER = "opp-trip-a-return-ship-b-reefer"
LATE = "opp-trip-a-return-ship-b-late"

GOOD_EXPLANATIONS = {
    MATCH: "Fits: 1,200 kg needed, 4,500 kg available, detour 6.1 km. Potential 361.0 kg CO2 "
           "avoided (estimate). Breaks if pickup slips past 12:00.",
    REEFER: "Rejected: needs refrigerated (2 to 6 °C) but the truck is ambient only.",
    LATE: "Rejected: pickup window 15:00–17:00 opens after the truck leaves.",
}


class FakeModels:
    """Mimics client.models.generate_content for both agent phases."""

    def __init__(self, explanations=None, summary="Checked 3 pairs: 1 feasible, 2 rejected.",
                 call_tools=True, fail_on=None):
        self.explanations = GOOD_EXPLANATIONS if explanations is None else explanations
        self.summary = summary
        self.call_tools = call_tools
        self.fail_on = fail_on
        self.models_used = []

    def generate_content(self, *, model, contents, config):
        self.models_used.append(model)
        if config.tools:  # investigate phase: act like automatic function calling
            if self.fail_on == "investigate":
                raise RuntimeError("429 rate limited")
            if self.call_tools:
                tools = {f.__name__: f for f in config.tools}
                for c in tools["list_candidates"]()["candidates"]:
                    tools["validate_candidate"](c["trip_id"], c["shipment_id"])
                tools["evaluate_routes"]("trip-a-return", "ship-b")
                tools["calculate_impact"]("trip-a-return", "ship-b")
            return SimpleNamespace(text="DONE")
        if self.fail_on == "explain":
            raise RuntimeError("bad JSON")
        assert "Scan facts" in contents
        body = {
            "summary": self.summary,
            "explanations": [{"opportunity_id": k, "explanation": v} for k, v in self.explanations.items()],
        }
        return SimpleNamespace(text=json.dumps(body))


def fake_client(**kwargs):
    return SimpleNamespace(models=FakeModels(**kwargs))


def all_opportunities(result):
    return {o.id: o for o in (*result.opportunities, *result.rejected)}


@pytest.fixture(autouse=True)
def fixed_model(monkeypatch):
    monkeypatch.setattr(agent_mod, "get_config", lambda: SimpleNamespace(gemini_model="test-model"))


def test_template_mode_without_gemini():
    result = run_agent_scan(use_gemini=False)
    assert result.mode == "template"
    assert result.model is None
    assert result.fallback_reason == "Gemini disabled"

    assert result.candidates_considered == 3
    assert [o.id for o in result.opportunities] == [MATCH]
    assert {o.id for o in result.rejected} == {REEFER, LATE}

    opps = all_opportunities(result)
    assert all(o.explanation for o in opps.values())
    assert "361.0 kg CO2" in opps[MATCH].explanation
    assert "CARGO_TEMP_UNSUPPORTED" in opps[REEFER].explanation
    assert "TIME_WINDOW_CONFLICT" in opps[LATE].explanation
    assert "1 feasible, 2 rejected" in result.agent_summary
    assert set(result.template_explanations) == {MATCH, REEFER, LATE}

    # Fixed tool order: list, 3 validations, then routes + impact for the match.
    assert [c["name"] for c in result.tool_calls] == [
        "list_candidates", "validate_candidate", "validate_candidate", "validate_candidate",
        "evaluate_routes", "calculate_impact",
    ]


def test_missing_key_uses_template(monkeypatch):
    monkeypatch.setattr(agent_mod, "get_gemini_client", lambda: None)
    result = run_agent_scan()
    assert result.mode == "template"
    assert result.fallback_reason == "GEMINI_API_KEY not set"


def test_gemini_mode_uses_gemini_text_and_tool_calls():
    client = fake_client()
    result = run_agent_scan(client=client)
    assert result.mode == "gemini"
    assert result.model == "test-model"
    assert client.models.models_used == ["test-model", "test-model"]
    assert result.fallback_reason is None
    assert result.template_explanations == []
    assert result.agent_summary == "Checked 3 pairs: 1 feasible, 2 rejected."

    opps = all_opportunities(result)
    for opp_id, text in GOOD_EXPLANATIONS.items():
        assert opps[opp_id].explanation == text
    assert len(result.tool_calls) == 6


def test_gemini_cannot_change_numbers_or_feasibility():
    result = run_agent_scan(client=fake_client())
    template = run_agent_scan(use_gemini=False)
    assert result.opportunities[0].impact == template.opportunities[0].impact
    assert [o.id for o in result.rejected] == [o.id for o in template.rejected]


def test_invented_number_falls_back_to_template():
    bad = dict(GOOD_EXPLANATIONS, **{MATCH: "Saves about 50% and 400 kg of CO2."})
    result = run_agent_scan(client=fake_client(explanations=bad, summary="Saves 999 km."))
    opps = all_opportunities(result)
    assert result.template_explanations == [MATCH]
    assert "400" not in opps[MATCH].explanation
    assert opps[REEFER].explanation == GOOD_EXPLANATIONS[REEFER]
    assert "999" not in result.agent_summary


def test_missing_explanation_gets_template():
    partial = {MATCH: GOOD_EXPLANATIONS[MATCH]}
    result = run_agent_scan(client=fake_client(explanations=partial))
    assert set(result.template_explanations) == {REEFER, LATE}
    assert all(o.explanation for o in all_opportunities(result).values())


def test_tool_calling_error_falls_back_cleanly():
    result = run_agent_scan(client=fake_client(fail_on="investigate"))
    assert result.mode == "template"
    assert "429" in result.fallback_reason
    assert len(result.tool_calls) == 6
    assert result.agent_summary


def test_no_tool_calls_falls_back():
    result = run_agent_scan(client=fake_client(call_tools=False))
    assert result.mode == "template"
    assert result.fallback_reason == "tool calling failed: Gemini made no tool calls"
    assert len(result.tool_calls) == 6


def test_explanation_error_keeps_gemini_tool_calls():
    result = run_agent_scan(client=fake_client(fail_on="explain"))
    assert result.mode == "gemini"
    assert "bad JSON" in result.fallback_reason
    assert set(result.template_explanations) == {MATCH, REEFER, LATE}


def test_result_is_json_safe():
    result = run_agent_scan(use_gemini=False)
    dumped = result.model_dump(mode="json")
    assert json.loads(json.dumps(dumped)) == dumped


@pytest.mark.parametrize(
    "text, ok",
    [
        ("1,200 kg needed, CO2 down", True),
        ("2-6 °C cargo", True),
        ("saves 361.0 kg", True),
        ("saves 361 kg", True),  # same value, different formatting
        ("about 49%", False),    # rounded from 48.8
        ("8 m3 load", True),     # unit digit isn't a number
    ],
)
def test_grounding(text, ok):
    allowed = {1200.0, 2.0, 6.0, 361.0, 48.8, 8.0}
    assert agent_mod._grounded(text, allowed) is ok
