from pydantic import Field

from .common import ContractModel, Location, TimeWindow
from .enums import TripLeg


class Trip(ContractModel):
    id: str = Field(min_length=1)
    org_id: str = Field(min_length=1)
    vehicle_id: str = Field(min_length=1)
    origin: Location
    destination: Location
    depart_window: TimeWindow
    arrive_window: TimeWindow
    distance_km: float = Field(ge=0)
    # Spare capacity on this leg (full vehicle capacity on an empty return).
    available_kg: float = Field(ge=0)
    available_m3: float = Field(ge=0)
    leg: TripLeg
