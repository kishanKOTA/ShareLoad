"""Agent scan: Gemini drives the tools, Python owns every number.

``run_agent_scan()`` works in two phases:

1. **Investigate.** Gemini gets the four ``AgentTools`` as function
   declarations in a chat and decides which to call. We run the loop ourselves
   with ``Chat.send_message`` (automatic function calling is off), so every
   call is capped, logged in ``tool_calls`` and answered with its result.
2. **Explain.** A second, tool-free call gets the scan facts (all from tool
   outputs) and returns JSON: one overall summary and a short explanation per
   opportunity. Feasible ones say why they matched and what could invalidate
   them; rejected ones say why they failed.

Gemini never produces the results themselves. ``opportunities`` and ``rejected``
always come from the deterministic scan, so a bad model turn can't change a
feasibility decision or a number.

**Guardrail (docs/PRD.md):** every number in Gemini's text must appear in the
facts it was given. Any explanation (or summary) that quotes another number is
replaced with the fixed template, and its id is listed in
``template_explanations``. The summary must also quote the best match's net
km, fuel and CO2 saved exactly; if it doesn't, the template summary is used
(``template_summary=True``).

**Cache:** each successful Gemini run is written to
``<data_dir>/last_agent_scan.json`` with a fingerprint of the input data.
``run_agent_scan(use_cached=True)`` (for the demo) returns that run without
calling Gemini, as long as the data hasn't changed since; otherwise it scans
live.

**Fallbacks:** no API key, a Gemini error, or Gemini calling no tools at all
switches to template mode. The tools are then called in a fixed order, so
``tool_calls`` is always complete and the scan never crashes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from app.matching.scan import DEMO_DIR, ScanResult, load_demo_data, scan_opportunities
from app.schemas import Check, Opportunity

from .config import get_config, get_gemini_client
from .tools import AgentTools

log = logging.getLogger(__name__)

# Upper bound on tool calls Gemini may make in one scan (3 candidates need ~6).
MAX_TOOL_CALLS = 25

CACHE_FILENAME = "last_agent_scan.json"

INVESTIGATE_PROMPT = """\
You are ShareLoad's matching agent. Find which trucks with spare capacity can
carry another company's shipment.

Steps:
1. Call list_candidates.
2. Call validate_candidate for every candidate pair.
3. For each feasible pair only, call evaluate_routes and then calculate_impact.

Never compute, estimate or round any number yourself. Only the tools produce
numbers. When you have called every needed tool, reply with the single word DONE.
"""

EXPLAIN_PROMPT = """\
You write short explanations for ShareLoad scan results. The JSON below holds
every fact you may use; it all comes from deterministic tools.

Rules:
- Use only numbers that appear in the JSON, written exactly as they appear
  there. Do not calculate, round, convert units or combine numbers.
- Feasible opportunity (1-3 sentences, under 60 words): why it matched, and
  what could invalidate it (e.g. a time window, capacity or route change).
- Rejected opportunity (1-2 sentences): which checks failed and why, from the
  failed checks' detail text.
- Say CO2 savings are an estimate ("potential CO2 avoided"), never measured
  or guaranteed.
- summary: 1-2 sentences on the whole scan. If "best_match" is present, the
  summary must name it and state its distance_km, fuel_l and co2_kg saved,
  copied exactly (e.g. "saves 123.4 km, 56.7 L of fuel and a potential
  89.0 kg CO2 avoided").
- Write one explanation for every opportunity_id in the JSON.

Scan facts:
"""


class AgentScanResult(ScanResult):
    agent_summary: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    mode: str = Field(description="gemini, or template when Gemini is unavailable")
    model: str | None = None
    fallback_reason: str | None = None
    # Opportunities whose explanation came from the template, not Gemini.
    template_explanations: list[str] = Field(default_factory=list)
    template_summary: bool = False
    # True when this result was loaded from the last-run cache.
    cached: bool = False


class _Explanation(BaseModel):
    opportunity_id: str
    explanation: str


class _ExplainResponse(BaseModel):
    summary: str
    explanations: list[_Explanation]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run_agent_scan(
    data_dir: Path = DEMO_DIR,
    client: Any | None = None,
    use_gemini: bool = True,
    use_cached: bool = False,
) -> AgentScanResult:
    """Scan for opportunities and explain them.

    ``client`` defaults to the configured Gemini client; pass ``use_gemini=False``
    to force template mode. ``use_cached=True`` returns the last successful
    Gemini run for this data, if there is one, without calling Gemini.
    """
    if use_cached:
        cached = load_cached_scan(data_dir)
        if cached is not None:
            return cached

    scan = scan_opportunities(data_dir)
    data = load_demo_data(data_dir)
    if client is None and use_gemini:
        client = get_gemini_client()
    model = get_config().gemini_model if client is not None else None

    tools = AgentTools(data)
    fallback_reason = None
    if client is None:
        fallback_reason = "GEMINI_API_KEY not set" if use_gemini else "Gemini disabled"

    if client is not None:
        try:
            _investigate(client, model, tools)
            if not tools.tool_calls:
                raise RuntimeError("Gemini made no tool calls")
        except Exception as exc:
            log.warning("Gemini tool calling failed (%s); using template mode", exc)
            fallback_reason = f"tool calling failed: {exc}"
            client, model = None, None
            tools = AgentTools(data)  # discard a partial log; rerun cleanly

    if client is None:
        _run_tools_in_order(tools, scan)

    facts = _facts(scan)
    summary, explanations = None, {}
    if client is not None:
        try:
            summary, explanations = _explain(client, model, facts)
        except Exception as exc:
            log.warning("Gemini explanation failed (%s); using templates", exc)
            fallback_reason = f"explanation failed: {exc}"

    allowed = _numbers_in(facts) | _numbers_in(tools.tool_calls)
    template_ids: list[str] = []
    for opportunity in (*scan.opportunities, *scan.rejected):
        text = explanations.get(opportunity.id)
        if text is None or not _grounded(text, allowed):
            if text is not None:
                log.warning("explanation for %s quotes ungrounded numbers; using template", opportunity.id)
            text = _template_explanation(opportunity)
            template_ids.append(opportunity.id)
        opportunity.explanation = text

    template_summary = False
    best = _best_match(scan)
    if summary is not None and not _grounded(summary, allowed):
        log.warning("summary quotes ungrounded numbers; using template")
        summary = None
    if summary is not None and best is not None and not _mentions_savings(summary, best):
        log.warning("summary omits the best match's km, fuel or CO2; using template")
        summary = None
    if summary is None:
        summary, template_summary = _template_summary(scan), True

    result = AgentScanResult(
        **scan.model_dump(),
        agent_summary=summary,
        tool_calls=tools.tool_calls,
        mode="gemini" if client is not None else "template",
        model=model,
        fallback_reason=fallback_reason,
        template_explanations=template_ids,
        template_summary=template_summary,
    )
    if result.mode == "gemini" and fallback_reason is None:
        _save_cache(data_dir, result)
    return result


# --------------------------------------------------------------------------- #
# Cache of the last successful Gemini run
# --------------------------------------------------------------------------- #


def _cache_path(data_dir: Path) -> Path:
    return Path(data_dir) / CACHE_FILENAME


def _data_fingerprint(data_dir: Path) -> str:
    """Hash of the scan inputs, so a cache from older data is never served."""
    digest = hashlib.sha256()
    for path in sorted(Path(data_dir).iterdir()):
        if path.name == CACHE_FILENAME or path.suffix not in (".json", ".geojson"):
            continue
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _save_cache(data_dir: Path, result: AgentScanResult) -> None:
    path = _cache_path(data_dir)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_fingerprint": _data_fingerprint(data_dir),
        "result": result.model_dump(mode="json"),
    }
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:  # a read-only checkout shouldn't break the scan
        log.warning("could not write agent scan cache %s (%s)", path, exc)
        tmp.unlink(missing_ok=True)


def load_cached_scan(data_dir: Path = DEMO_DIR) -> AgentScanResult | None:
    """The last successful Gemini run, or None if missing, unreadable or stale."""
    path = _cache_path(data_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("data_fingerprint") != _data_fingerprint(data_dir):
            log.info("agent scan cache %s is from older data; scanning live", path)
            return None
        return AgentScanResult.model_validate({**payload["result"], "cached": True})
    except Exception as exc:
        log.warning("ignoring unreadable agent scan cache %s (%s)", path, exc)
        return None


# --------------------------------------------------------------------------- #
# Gemini phases
# --------------------------------------------------------------------------- #


def _investigate(client: Any, model: str, tools: AgentTools) -> None:
    """Let Gemini call the tools in a chat; we run each call and send back the result.

    Tools go in as declarations with automatic function calling disabled, so
    the SDK never executes anything itself (and doesn't log its AFC notice).
    """
    from google.genai import types

    functions = {f.__name__: f for f in tools.as_functions()}
    declarations = [
        types.FunctionDeclaration.from_callable_with_api_option(callable=f)
        for f in functions.values()
    ]
    chat = client.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=declarations)],
            temperature=0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    response = chat.send_message(INVESTIGATE_PROMPT)
    calls = 0
    while response.function_calls:
        replies = []
        for call in response.function_calls:
            if calls >= MAX_TOOL_CALLS:
                log.warning("Gemini hit the %d tool-call limit; stopping", MAX_TOOL_CALLS)
                return
            calls += 1
            replies.append(
                types.Part.from_function_response(
                    name=call.name, response=_run_tool(functions, call.name, call.args)
                )
            )
        response = chat.send_message(replies)


def _run_tool(functions: dict[str, Any], name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    fn = functions.get(name)
    if fn is None:
        return {"error": f"unknown tool {name!r}"}
    try:
        return fn(**(args or {}))
    except TypeError as exc:  # wrong or missing arguments from the model
        return {"error": f"bad arguments for {name}: {exc}"}


def _explain(client: Any, model: str, facts: dict[str, Any]) -> tuple[str, dict[str, str]]:
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=EXPLAIN_PROMPT + json.dumps(facts, ensure_ascii=False, indent=1),
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=_ExplainResponse,
        ),
    )
    parsed = _ExplainResponse.model_validate_json(response.text)
    return parsed.summary.strip(), {
        e.opportunity_id: e.explanation.strip() for e in parsed.explanations if e.explanation.strip()
    }


def _run_tools_in_order(tools: AgentTools, scan: ScanResult) -> None:
    """Template mode: the same tool sequence the prompt asks Gemini for."""
    tools.list_candidates()
    for opportunity in (*scan.opportunities, *scan.rejected):
        tools.validate_candidate(opportunity.trip_id, opportunity.shipment_id)
    for opportunity in scan.opportunities:
        tools.evaluate_routes(opportunity.trip_id, opportunity.shipment_id)
        tools.calculate_impact(opportunity.trip_id, opportunity.shipment_id)


# --------------------------------------------------------------------------- #
# Facts and guardrail
# --------------------------------------------------------------------------- #


def _facts(scan: ScanResult) -> dict[str, Any]:
    """Everything the explainer may cite, without map geometry or formula trace."""

    def entry(o: Opportunity) -> dict[str, Any]:
        item: dict[str, Any] = {
            "opportunity_id": o.id,
            "trip_id": o.trip_id,
            "shipment_id": o.shipment_id,
            "feasible": o.feasible,
            "reason_codes": [c.value for c in o.reason_codes],
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in o.checks],
        }
        if o.baseline and o.shared:
            item["baseline_km"] = o.baseline.distance_km
            item["shared_km"] = o.shared.distance_km
            item["detour_km"] = o.shared.detour_km
        if o.impact:
            item["net_saved"] = o.impact.net_saved.model_dump()
            item["reduction_pct"] = o.impact.reduction_pct
            item["recommended"] = o.impact.recommended
        return item

    facts: dict[str, Any] = {
        "candidates_considered": scan.candidates_considered,
        "feasible_count": len(scan.opportunities),
        "rejected_count": len(scan.rejected),
        "opportunities": [entry(o) for o in (*scan.opportunities, *scan.rejected)],
    }
    best = _best_match(scan)
    if best is not None:
        net = best.impact.net_saved
        facts["best_match"] = {
            "opportunity_id": best.id,
            "distance_km": net.distance_km,
            "fuel_l": net.fuel_l,
            "co2_kg": net.co2_kg,
            "reduction_pct": best.impact.reduction_pct,
        }
    return facts


def _best_match(scan: ScanResult) -> Opportunity | None:
    """First recommended opportunity; the scan already sorts best CO2 saving first."""
    return next((o for o in scan.opportunities if o.impact and o.impact.recommended), None)


def _mentions_savings(text: str, best: Opportunity) -> bool:
    """The text states the best match's net km, fuel and CO2 saved."""
    net = best.impact.net_saved
    return {float(net.distance_km), float(net.fuel_l), float(net.co2_kg)} <= _extract_numbers(text)


# A number like 1,200 or 48.8 or -3; "CO2" is stripped first so its 2 isn't counted.
_NUMBER = re.compile(r"(?<![\w.])-?[0-9][0-9,]*(?:\.[0-9]+)?")
_CHEMICAL = re.compile(r"CO2", re.IGNORECASE)


def _extract_numbers(text: str) -> set[float]:
    text = _CHEMICAL.sub("", text)
    out = set()
    for match in _NUMBER.findall(text):
        try:
            out.add(float(match.replace(",", "")))
        except ValueError:
            pass
    return out


def _numbers_in(value: Any) -> set[float]:
    """Every number in a JSON-like value, including numbers inside strings."""
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {float(value)}
    if isinstance(value, str):
        return _extract_numbers(value)
    if isinstance(value, dict):
        return set().union(*(_numbers_in(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(_numbers_in(v) for v in value)) if value else set()
    return set()


def _grounded(text: str, allowed: set[float]) -> bool:
    return _extract_numbers(text) <= allowed


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


def _check(o: Opportunity, name: str) -> Check | None:
    return next((c for c in o.checks if c.name == name), None)


def _join(parts: Iterable[str]) -> str:
    return "; ".join(p for p in parts if p)


def _template_explanation(o: Opportunity) -> str:
    if not o.feasible:
        failed = [f"{c.name.replace('_', ' ')}: {c.detail}" for c in o.checks if not c.passed]
        return f"Rejected ({', '.join(c.value for c in o.reason_codes)}). {_join(failed)}."

    weight, detour, pickup = (_check(o, n) for n in ("weight_capacity", "detour", "pickup_window"))
    why = f"{o.shipment_id} fits on {o.trip_id}: all {len(o.checks)} checks passed"
    if weight:
        why += f" ({weight.detail})"
    text = why + "."
    if o.impact:
        net = o.impact.net_saved
        if o.impact.recommended:
            text += (
                f" Sharing cuts total driving from {o.impact.baseline.distance_km:,.1f} km to "
                f"{o.impact.shared.distance_km:,.1f} km, a potential {net.co2_kg:,.1f} kg CO2 "
                f"avoided (estimate)."
            )
        else:
            text += " Sharing would add driving overall, so it is not recommended."
    risks = _join([
        f"pickup timing changes (pickup {pickup.detail})" if pickup else "",
        f"the detour grows ({detour.detail})" if detour else "",
        "the load grows past spare capacity",
    ])
    return text + f" Could be invalidated if {risks}."


def _template_summary(scan: ScanResult) -> str:
    n, k, r = scan.candidates_considered, len(scan.opportunities), len(scan.rejected)
    text = f"Checked {n} candidate pair(s): {k} feasible, {r} rejected."
    best = _best_match(scan)
    if best:
        net = best.impact.net_saved
        text += (
            f" Best match {best.id} saves {net.distance_km:,.1f} vehicle-km "
            f"({best.impact.reduction_pct:g}%), {net.fuel_l:,.1f} L of fuel and a potential "
            f"{net.co2_kg:,.1f} kg CO2 avoided (estimate)."
        )
    elif k == 0:
        text += " No shareable loads found."
    return text
