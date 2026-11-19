from pydantic import Field

from .common import ContractModel


class Organization(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    is_sample: bool = True
