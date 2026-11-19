"""Shipment schema.

Shipments can come from Gemini free-text extraction, so the fields the matcher
depends on are optional: a missing value is ``None`` and is listed in
``extraction.missing_fields``. The validator turns those into
``MISSING_CRITICAL_FIELD`` rather than the schema rejecting the record.
"""

from pydantic import Field, model_validator

from .common import ContractModel, Location, TimeWindow
from .enums import CargoType

CRITICAL_FIELDS: tuple[str, ...] = (
    "origin",
    "destination",
    "weight_kg",
    "volume_m3",
    "cargo_type",
    "hazardous",
    "pickup_window",
    "delivery_window",
)


class ExtractionInfo(ContractModel):
    confidence: float = Field(ge=0, le=1)
    missing_fields: list[str] = Field(default_factory=list)


class Shipment(ContractModel):
    id: str = Field(min_length=1)
    org_id: str = Field(min_length=1)
    origin: Location | None = None
    destination: Location | None = None
    weight_kg: float | None = Field(default=None, gt=0)
    volume_m3: float | None = Field(default=None, gt=0)
    cargo_type: CargoType | None = None
    hazardous: bool | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    pickup_window: TimeWindow | None = None
    delivery_window: TimeWindow | None = None
    raw_text: str | None = None
    # None for shipments loaded directly from fixtures (not extracted).
    extraction: ExtractionInfo | None = None

    @model_validator(mode="after")
    def _temp_range_ordered(self) -> "Shipment":
        if (
            self.temp_min_c is not None
            and self.temp_max_c is not None
            and self.temp_min_c > self.temp_max_c
        ):
            raise ValueError("temp_min_c must not exceed temp_max_c")
        return self

    def missing_critical_fields(self) -> list[str]:
        """Critical fields that are unset, whether or not extraction flagged them."""
        return [name for name in CRITICAL_FIELDS if getattr(self, name) is None]
