"""Building blocks reused by several entity schemas.

Units across all contracts: km, kg, m³, litres, ISO-8601 datetimes with timezone.
"""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Base for every contract model.

    ``extra="forbid"`` makes fixtures or mock JSON that drift from the frozen
    contract fail loudly instead of silently dropping fields.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Location(ContractModel):
    name: str = Field(min_length=1, examples=["Chicago, IL"])
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class TimeWindow(ContractModel):
    """Inclusive window; both ends must carry a timezone offset."""

    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "TimeWindow":
        if self.end < self.start:
            raise ValueError("time window end must not be before start")
        return self

    def overlaps(self, other: "TimeWindow") -> bool:
        return self.start <= other.end and other.start <= self.end
