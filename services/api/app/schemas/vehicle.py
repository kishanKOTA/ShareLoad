from pydantic import Field

from .common import ContractModel
from .enums import CargoType


class Vehicle(ContractModel):
    id: str = Field(min_length=1)
    org_id: str = Field(min_length=1)
    type: str = Field(min_length=1, examples=["box_truck"])
    payload_kg: float = Field(gt=0)
    volume_m3: float = Field(gt=0)
    # Cargo types this vehicle can carry, e.g. ["ambient"] for a dry box truck.
    capabilities: list[CargoType] = Field(default_factory=list)
    # Single rate for loaded and empty running (stated simplification in the PRD).
    fuel_l_per_100km: float = Field(gt=0)

    def can_carry(self, cargo_type: CargoType) -> bool:
        return cargo_type in self.capabilities
