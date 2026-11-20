from enum import Enum
from typing import Any

from pydantic import AwareDatetime, Field

from .common import ContractModel


class Actor(str, Enum):
    AGENT = "agent"
    USER = "user"


class AuditEvent(ContractModel):
    id: str = Field(min_length=1)
    # The acting organization; None for agent events that belong to no single org.
    org_id: str | None = None
    actor: Actor
    event_type: str = Field(min_length=1, examples=["proposal.created"])
    # "<kind>:<id>", e.g. "proposal:prop-1" or "opportunity:opp-...".
    entity: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime
