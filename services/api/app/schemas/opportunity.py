"""Opportunity schema: one trip/shipment pairing, its checks, routes and impact.

Infeasible candidates still produce an Opportunity (feasible=False with reason
codes) so the UI can show what was rejected and why; route and impact data may
be absent for those.
"""

from typing import Any

from pydantic import Field, model_validator

from .common import ContractModel
from .enums import ReasonCode


class Check(ContractModel):
    """One row of the constraint checklist shown on the Opportunity detail page."""

    name: str = Field(min_length=1, examples=["weight_capacity"])
    passed: bool
    reason_code: ReasonCode | None = None
    detail: str = Field(default="", examples=["1,200 kg needed, 4,500 kg available"])

    @model_validator(mode="after")
    def _failed_checks_have_code(self) -> "Check":
        if not self.passed and self.reason_code is None:
            raise ValueError("a failed check must carry a reason_code")
        if self.passed and self.reason_code is not None:
            raise ValueError("a passed check must not carry a reason_code")
        return self


class RouteScenario(ContractModel):
    """Total vehicle movement across both businesses for one scenario."""

    description: str = Field(examples=["A round trip + B hired round trip"])
    distance_km: float = Field(ge=0)
    detour_km: float = Field(default=0, ge=0)
    # GeoJSON FeatureCollection (cached OSRM geometry), passed through to the map.
    geometry: dict[str, Any] | None = None


class ScenarioMetrics(ContractModel):
    distance_km: float
    fuel_l: float
    co2_kg: float
    cost_usd: float


class FormulaStep(ContractModel):
    """One line of the formula trace behind an impact number."""

    label: str = Field(examples=["Baseline fuel"])
    formula: str = Field(examples=["960 km × 26 L/100 km ÷ 100"])
    value: float
    unit: str = Field(examples=["L"])


class Impact(ContractModel):
    baseline: ScenarioMetrics
    shared: ScenarioMetrics
    # baseline − shared; may be negative, which is shown honestly as "not recommended".
    net_saved: ScenarioMetrics
    reduction_pct: float
    recommended: bool
    formula_trace: list[FormulaStep] = Field(default_factory=list)
    assumptions_version: str


class Opportunity(ContractModel):
    id: str = Field(min_length=1)
    trip_id: str = Field(min_length=1)
    shipment_id: str = Field(min_length=1)
    feasible: bool
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    baseline: RouteScenario | None = None
    shared: RouteScenario | None = None
    impact: Impact | None = None
    score: float | None = None
    explanation: str | None = None

    @model_validator(mode="after")
    def _feasibility_consistent(self) -> "Opportunity":
        if self.feasible and self.reason_codes:
            raise ValueError("a feasible opportunity must not have reason_codes")
        if not self.feasible and not self.reason_codes:
            raise ValueError("an infeasible opportunity needs at least one reason_code")
        return self
