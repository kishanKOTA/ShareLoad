"""Gemini free-text shipment extraction.

``extract_shipment`` sends the raw text to Gemini with a JSON response schema
and turns the reply into a schema-valid :class:`~app.schemas.Shipment`. Gemini
only reads the text: it fills in fields, a confidence and the fields it could
not find. Python then validates the result against the Shipment contract.

A reply that isn't valid JSON, or that doesn't fit the Shipment contract (for
example a datetime without a timezone), is retried once. A second bad reply
raises :class:`ExtractionFailed`, so the caller can fall back to a manual form.

``missing_fields`` in the result lists the critical fields (``CRITICAL_FIELDS``,
in that order) that Gemini flagged or that are actually unset. Values
Gemini didn't give stay ``None``; nothing is guessed in Python.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agent.config import get_config
from app.schemas import CRITICAL_FIELDS, CargoType, ExtractionInfo, Shipment

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # first try + one retry on bad JSON / schema-invalid output
MAX_RAW_TEXT = 20_000


class ExtractionUnavailable(Exception):
    """Gemini is not configured (no API key), so extraction can't run."""


class ExtractionFailed(Exception):
    """Gemini errored or returned unusable output on every attempt."""


class ParseShipmentRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=MAX_RAW_TEXT)


# --- Gemini response schema -------------------------------------------------
# Kept separate from Shipment: Gemini fills plain strings/numbers, and Python
# converts and validates them against the frozen contract.


class _ExtractedLocation(BaseModel):
    name: str = Field(description="Place as written, e.g. 'Lakeview Supply warehouse, Chicago, IL'")
    lat: float = Field(description="Approximate latitude of the place (city-level is fine)")
    lon: float = Field(description="Approximate longitude of the place (city-level is fine)")


class _ExtractedWindow(BaseModel):
    start: str = Field(description="ISO-8601 datetime with UTC offset, e.g. 2026-11-20T08:00:00-06:00")
    end: str = Field(description="ISO-8601 datetime with UTC offset")


class _ExtractedShipment(BaseModel):
    origin: _ExtractedLocation | None = None
    destination: _ExtractedLocation | None = None
    weight_kg: float | None = Field(default=None, description="Total weight in kilograms")
    volume_m3: float | None = Field(default=None, description="Total volume in cubic meters")
    cargo_type: CargoType | None = None
    hazardous: bool | None = None
    temp_min_c: float | None = Field(default=None, description="Only for temperature-controlled cargo")
    temp_max_c: float | None = Field(default=None, description="Only for temperature-controlled cargo")
    pickup_window: _ExtractedWindow | None = None
    delivery_window: _ExtractedWindow | None = None
    confidence: float = Field(description="0 to 1: how confident you are in the extracted values overall")
    missing_fields: list[str] = Field(
        default_factory=list, description="Fields the text does not state (left null)"
    )


EXTRACT_PROMPT = """\
You extract a freight shipment request from free text (usually an email) into JSON.

Rules:
- Use only what the text states. If a field is not stated or cannot be inferred
  with confidence, set it to null and list its name in missing_fields.
- Convert units: weight to kilograms (1 lb = 0.4536 kg), volume to cubic meters
  (1 ft3 = 0.0283 m3).
- cargo_type is one of: {cargo_types}. Shelf-stable / dry goods are "ambient".
- hazardous is true or false only when the text says so (e.g. "nothing hazardous" -> false).
- temp_min_c / temp_max_c only for refrigerated or frozen cargo, in Celsius.
- Times are ISO-8601 with a UTC offset. Resolve dates like "this Friday" from
  the message date if present, otherwise from today's date ({today}). Use the
  timezone the text names (e.g. Central = -06:00 in winter, -05:00 in summer);
  if none is named, list the window in missing_fields.
- origin/destination: the place name as written, plus approximate lat/lon.
- confidence: 0 to 1 for the extraction as a whole; lower it for guesses.
- Field names for missing_fields: {fields}.

Text:
"""


def extract_shipment(
    raw_text: str,
    org_id: str,
    client: Any | None,
    *,
    model: str | None = None,
    now: datetime | None = None,
    shipment_id: str | None = None,
) -> Shipment:
    """Extract a Shipment for ``org_id`` from ``raw_text`` using Gemini ``client``.

    Raises ExtractionUnavailable when ``client`` is None, and ExtractionFailed
    when Gemini errors or returns bad output twice.
    """
    if client is None:
        raise ExtractionUnavailable("GEMINI_API_KEY is not set")
    from google.genai import types

    model = model or get_config().gemini_model
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    prompt = EXTRACT_PROMPT.format(
        cargo_types=", ".join(c.value for c in CargoType),
        today=today,
        fields=", ".join(CRITICAL_FIELDS),
    ) + raw_text
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_schema=_ExtractedShipment,
    )

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
        except Exception as exc:  # network, quota, auth: not a bad-JSON case, don't retry
            raise ExtractionFailed(f"Gemini request failed: {exc}") from exc
        try:
            return _to_shipment(response.text, raw_text, org_id, shipment_id)
        except (ValueError, ValidationError, TypeError) as exc:
            last_error = exc
            log.warning("Extraction attempt %d returned bad output: %s", attempt, exc)
    raise ExtractionFailed(
        f"Gemini returned invalid shipment JSON after {MAX_ATTEMPTS} attempts: {last_error}"
    )


def _to_shipment(text: str | None, raw_text: str, org_id: str, shipment_id: str | None) -> Shipment:
    if not text:
        raise ValueError("empty response")
    extracted = _ExtractedShipment.model_validate(json.loads(text))
    fields = extracted.model_dump(exclude={"confidence", "missing_fields"})
    flagged = set(extracted.missing_fields) | {f for f in CRITICAL_FIELDS if fields[f] is None}
    return Shipment(
        id=shipment_id or f"ship-{uuid.uuid4().hex[:8]}",
        org_id=org_id,
        raw_text=raw_text,
        extraction=ExtractionInfo(
            confidence=extracted.confidence,
            missing_fields=[f for f in CRITICAL_FIELDS if f in flagged],
        ),
        **fields,
    )
