"""Agent scan tests. Gemini is replaced by a fake client; no network calls."""

import json
import shutil
from types import SimpleNamespace

import pytest

from app.agent import agent as agent_mod
from app.agent.agent import CACHE_FILENAME, load_cached_scan, run_agent_scan
from app.matching.scan import DEMO_DIR

MATCH = "opp-trip-a-return-ship-b"
REEFER = "opp-trip-a-return-ship-b-reefer"
LATE = "opp-trip-a-return-ship-b-late"

GOOD_EXPLANATIONS = {
    MATCH: "Fits: 1,200 kg needed, 4,500 kg available, detour 6.1 km. Potential 323.6 kg CO2 "
           "avoided (estimate). Breaks if pickup slips past 12:00.",
    REEFER: "Rejected: needs refrigerated (2 to 6 °C) but the truck is ambient only.",
    LATE: "Rejected: pickup window 15:00–17:00 opens after the truck leaves.",
}


GOOD_SUMMARY = ("Checked 3 pairs: 1 feasible, 2 rejected. The best match saves 461.0 km, "
                "119.9 L of fuel and a potential 323.6 kg CO2 avoided (estimate).")


def call(name, **args):
    return SimpleNamespace(name=name, args=args)


def reply(*calls, text=None):
    return SimpleNamespace(function_calls=list(calls) or None, text=text)


class FakeChat:
    """Mimics Chat.send_message with manual function calling.

    Turn 1 asks for list_candidates; once it sees that result it asks to
    validate every candidate, then for routes + impact on the match, then DONE.
    """

    def __init__(self, owner, config):
        self.owner = owner
        self.config = config
        self.turn = 0
        self.responses = []  # function responses Gemini received, per turn

    def send_message(self, message):
        self.turn += 1
        if self.owner.fail_on == "investigate":
            raise RuntimeError("429 rate limited")
        if isinstance(message, str):
            assert "matching agent" in message
            return reply(call("list_candidates")) if self.owner.call_tools else reply(text="DONE")
        received = {p.function_response.name: p.function_response.response for p in message}
        self.responses.append(received)
        if "list_candidates" in received:
            return reply(*(
                call("validate_candidate", trip_id=c["trip_id"], shipment_id=c["shipment_id"])
                for c in received["list_candidates"]["candidates"]
            ))
        if "validate_candidate" in received:
            ids = dict(trip_id="trip-a-return", shipment_id="ship-b")
            return reply(call("evaluate_routes", **ids), call("calculate_impact", **ids))
        return reply(text="DONE")


class FakeChats:
    def __init__(self, owner):
        self.owner = owner
        self.created = []

    def create(self, *, model, config):
        self.owner.models_used.append(model)
        # Manual loop: tools are declarations and AFC is off.
        assert config.automatic_function_calling.disable is True
        names = [d.name for t in config.tools for d in t.function_declarations]
        assert names == ["list_candidates", "validate_candidate", "evaluate_routes", "calculate_impact"]
        chat = self.owner.chat_factory(self.owner, config)
        self.created.append(chat)
        return chat


class FakeModels:
    """Mimics client.models.generate_content for the explain phase."""

    def __init__(self, explanations=None, summary=GOOD_SUMMARY, call_tools=True, fail_on=None,
                 chat_factory=FakeChat):
        self.explanations = GOOD_EXPLANATIONS if explanations is None else explanations
        self.summary = summary
        self.call_tools = call_tools
        self.fail_on = fail_on
        self.chat_factory = chat_factory
        self.models_used = []
        self.explain_prompts = []

    def generate_content(self, *, model, contents, config):
        self.models_used.append(model)
        assert not config.tools
        self.explain_prompts.append(contents)
        if self.fail_on == "explain":
            raise RuntimeError("bad JSON")
        assert "Scan facts" in contents
        body = {
            "summary": self.summary,
            "explanations": [{"opportunity_id": k, "explanation": v} for k, v in self.explanations.items()],
        }
        return SimpleNamespace(text=json.dumps(body))


def fake_client(**kwargs):
    models = FakeModels(**kwargs)
    return SimpleNamespace(models=models, chats=FakeChats(models))


def all_opportunities(result):
    return {o.id: o for o in (*result.opportunities, *result.rejected)}


@pytest.fixture(autouse=True)
def fixed_model(monkeypatch):
    monkeypatch.setattr(agent_mod, "get_config", lambda: SimpleNamespace(gemini_model="test-model"))


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    """Keep tests from writing the real data/demo cache."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(agent_mod, "_cache_path", lambda data_dir: cache_dir / CACHE_FILENAME)
    return cache_dir / CACHE_FILENAME


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
    assert "323.6 kg CO2" in opps[MATCH].explanation
    assert "CARGO_TEMP_UNSUPPORTED" in opps[REEFER].explanation
    assert "TIME_WINDOW_CONFLICT" in opps[LATE].explanation
    assert "1 feasible, 2 rejected" in result.agent_summary
    for number in ("461.0 vehicle-km", "119.9 L of fuel", "323.6 kg CO2"):
        assert number in result.agent_summary
    assert result.template_summary is True
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
    assert result.template_summary is False
    assert result.agent_summary == GOOD_SUMMARY

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
        ("saves 323.6 kg", True),
        ("saves 1200 kg", True),  # same value as 1,200, different formatting
        ("about 49%", False),    # rounded from 48.8
        ("8 m3 load", True),     # unit digit isn't a number
    ],
)
def test_grounding(text, ok):
    allowed = {1200.0, 2.0, 6.0, 323.6, 48.8, 8.0}
    assert agent_mod._grounded(text, allowed) is ok


# --------------------------------------------------------------------------- #
# Chat function-calling loop
# --------------------------------------------------------------------------- #


def test_chat_loop_returns_tool_results_to_gemini():
    client = fake_client()
    result = run_agent_scan(client=client)
    chat = client.chats.created[0]
    assert chat.turn == 4  # prompt, candidates, validations, routes+impact
    validations = chat.responses[1]
    assert validations["validate_candidate"]["feasible"] in (True, False)
    impact = chat.responses[2]["calculate_impact"]
    assert impact["net_saved"]["co2_kg"] == result.opportunities[0].impact.net_saved.co2_kg
    assert [c["name"] for c in result.tool_calls] == [
        "list_candidates", "validate_candidate", "validate_candidate", "validate_candidate",
        "evaluate_routes", "calculate_impact",
    ]


class BadCallsChat(FakeChat):
    """Asks for an unknown tool and passes bad arguments, then stops."""

    def send_message(self, message):
        self.turn += 1
        if isinstance(message, str):
            return reply(call("list_candidates"), call("delete_everything"),
                         call("validate_candidate", trip="x"))
        self.responses.append({p.function_response.name: p.function_response.response for p in message})
        return reply(text="DONE")


def test_unknown_tool_and_bad_args_are_reported_not_raised():
    client = fake_client(chat_factory=BadCallsChat)
    result = run_agent_scan(client=client)
    sent = client.chats.created[0].responses[0]
    assert "unknown tool" in sent["delete_everything"]["error"]
    assert "bad arguments" in sent["validate_candidate"]["error"]
    assert result.mode == "gemini"
    assert [c["name"] for c in result.tool_calls] == ["list_candidates"]


class EndlessChat(FakeChat):
    def send_message(self, message):
        self.turn += 1
        return reply(call("list_candidates"))


def test_tool_call_limit_stops_the_loop():
    client = fake_client(chat_factory=EndlessChat)
    result = run_agent_scan(client=client)
    assert len(result.tool_calls) == agent_mod.MAX_TOOL_CALLS
    assert result.mode == "gemini"


# --------------------------------------------------------------------------- #
# Summary must cite the best match's savings
# --------------------------------------------------------------------------- #


def test_explain_facts_include_best_match():
    client = fake_client()
    run_agent_scan(client=client)
    facts = json.loads(client.models.explain_prompts[0].split("Scan facts:\n", 1)[1])
    assert facts["best_match"] == {
        "opportunity_id": MATCH, "distance_km": 461.0, "fuel_l": 119.9,
        "co2_kg": 323.6, "reduction_pct": 48.8,
    }


@pytest.mark.parametrize(
    "summary",
    [
        "Checked 3 pairs: 1 feasible, 2 rejected.",                                  # no savings
        "Best match saves 461.0 km and a potential 323.6 kg CO2 avoided (estimate).",  # no fuel
        "Best match saves 461.0 km and 119.9 L of fuel.",                            # no CO2
    ],
)
def test_summary_missing_best_match_savings_uses_template(summary):
    result = run_agent_scan(client=fake_client(summary=summary))
    assert result.template_summary is True
    assert result.agent_summary != summary
    for number in ("461.0", "119.9", "323.6"):
        assert number in result.agent_summary


def test_summary_with_savings_but_invented_number_uses_template():
    summary = GOOD_SUMMARY + " That is about 50% less."
    result = run_agent_scan(client=fake_client(summary=summary))
    assert result.template_summary is True
    assert "50%" not in result.agent_summary


def test_summary_accepts_reformatted_savings():
    summary = "Best match saves 461 km, 119.9 L fuel and potentially 323.6 kg CO2 (estimate)."
    result = run_agent_scan(client=fake_client(summary=summary))
    assert result.template_summary is False
    assert result.agent_summary == summary


# --------------------------------------------------------------------------- #
# Cache of the last successful Gemini run
# --------------------------------------------------------------------------- #


def test_successful_gemini_run_is_cached(isolated_cache):
    live = run_agent_scan(client=fake_client())
    payload = json.loads(isolated_cache.read_text(encoding="utf-8"))
    assert payload["result"]["agent_summary"] == GOOD_SUMMARY
    assert payload["data_fingerprint"]

    cached = run_agent_scan(use_cached=True, use_gemini=False)
    assert cached.cached is True
    assert cached.mode == "gemini"
    assert cached.agent_summary == live.agent_summary
    assert cached.model_dump(exclude={"cached"}) == live.model_dump(exclude={"cached"})


def test_use_cached_makes_no_gemini_calls(isolated_cache):
    run_agent_scan(client=fake_client())
    client = fake_client()
    result = run_agent_scan(client=client, use_cached=True)
    assert result.cached is True
    assert client.models.models_used == []


@pytest.mark.parametrize(
    "kwargs",
    [dict(use_gemini=False), dict(fail_on="investigate"), dict(fail_on="explain")],
    ids=["template", "tool-calling-error", "explain-error"],
)
def test_failed_or_template_runs_are_not_cached(isolated_cache, kwargs):
    if kwargs.get("use_gemini") is False:
        run_agent_scan(**kwargs)
    else:
        run_agent_scan(client=fake_client(**kwargs))
    assert not isolated_cache.exists()


def test_failed_run_keeps_previous_cache(isolated_cache):
    run_agent_scan(client=fake_client())
    before = isolated_cache.read_text(encoding="utf-8")
    run_agent_scan(client=fake_client(fail_on="explain"))
    assert isolated_cache.read_text(encoding="utf-8") == before


def test_use_cached_without_cache_scans_live():
    result = run_agent_scan(use_cached=True, use_gemini=False)
    assert result.cached is False
    assert result.mode == "template"


def test_corrupt_cache_is_ignored(isolated_cache):
    isolated_cache.write_text("{not json", encoding="utf-8")
    assert load_cached_scan() is None
    assert run_agent_scan(use_cached=True, use_gemini=False).cached is False


def test_stale_cache_is_ignored_after_data_changes(monkeypatch, tmp_path):
    data_dir = tmp_path / "demo"
    shutil.copytree(DEMO_DIR, data_dir, ignore=shutil.ignore_patterns(CACHE_FILENAME))
    # Use the real cache location (inside data_dir) for this test.
    monkeypatch.setattr(agent_mod, "_cache_path", lambda d: d / CACHE_FILENAME)

    run_agent_scan(data_dir=data_dir, client=fake_client())
    assert (data_dir / CACHE_FILENAME).exists()
    assert load_cached_scan(data_dir) is not None

    assumptions = data_dir / "assumptions.json"
    assumptions.write_text(assumptions.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert load_cached_scan(data_dir) is None
