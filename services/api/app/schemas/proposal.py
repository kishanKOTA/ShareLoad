from enum import Enum
from typing import Any

from pydantic import AwareDatetime, Field

from .common import ContractModel
from .enums import ProposalStatus


class DecisionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class DecisionRequest(ContractModel):
    decision: DecisionType
    comment: str | None = None


class Decision(ContractModel):
    org_id: str = Field(min_length=1)
    decision: DecisionType
    comment: str | None = None
    decided_at: AwareDatetime


class Proposal(ContractModel):
    id: str = Field(min_length=1)
    opportunity_id: str = Field(min_length=1)
    status: ProposalStatus
    # Bumped on every state change so clients can spot stale copies.
    version: int = Field(ge=1)
    # The opportunity as it was when proposed; later rescans don't change it.
    snapshot: dict[str, Any]
    # The two organizations that must both approve: trip owner and shipment owner.
    parties: list[str] = Field(min_length=2, max_length=2)
    decisions: list[Decision] = Field(default_factory=list)
    created_by: str = Field(min_length=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
