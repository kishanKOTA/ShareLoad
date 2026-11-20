"""In-memory proposals with two-sided approval.

A proposal is created from a feasible opportunity and starts in
``pending_approvals``. Its two parties are the trip's org and the shipment's
org. Each party decides once:

* any ``reject``                     -> ``rejected``
* one ``approve``, other undecided   -> ``partially_approved``
* both ``approve``                   -> ``approved_for_external_coordination``

``rejected`` and ``approved_for_external_coordination`` are final. Every change
bumps ``version``. Only one open (non-rejected) proposal per opportunity.
"""

from __future__ import annotations

import itertools
import threading
from datetime import datetime, timezone

from app.schemas import (
    Decision,
    DecisionType,
    Opportunity,
    Proposal,
    ProposalStatus,
)

FINAL_STATUSES = frozenset(
    {ProposalStatus.REJECTED, ProposalStatus.APPROVED_FOR_EXTERNAL_COORDINATION}
)


class ProposalNotFound(Exception):
    pass


class ProposalForbidden(Exception):
    pass


class ProposalConflict(Exception):
    pass


def next_status(parties: list[str], decisions: list[Decision]) -> ProposalStatus:
    if any(d.decision == DecisionType.REJECT for d in decisions):
        return ProposalStatus.REJECTED
    approved = {d.org_id for d in decisions if d.decision == DecisionType.APPROVE}
    if approved >= set(parties):
        return ProposalStatus.APPROVED_FOR_EXTERNAL_COORDINATION
    if approved:
        return ProposalStatus.PARTIALLY_APPROVED
    return ProposalStatus.PENDING_APPROVALS


class ProposalStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proposals: dict[str, Proposal] = {}
        self._ids = itertools.count(1)

    def create(self, opportunity: Opportunity, parties: list[str], created_by: str) -> Proposal:
        if not opportunity.feasible:
            raise ProposalConflict("Only feasible opportunities can be proposed")
        if created_by not in parties:
            raise ProposalForbidden("Only the trip or shipment owner can propose this match")
        with self._lock:
            for p in self._proposals.values():
                if p.opportunity_id == opportunity.id and p.status != ProposalStatus.REJECTED:
                    raise ProposalConflict(
                        f"Opportunity already has open proposal {p.id!r}"
                    )
            now = datetime.now(timezone.utc)
            proposal = Proposal(
                id=f"prop-{next(self._ids)}",
                opportunity_id=opportunity.id,
                status=ProposalStatus.PENDING_APPROVALS,
                version=1,
                snapshot=opportunity.model_dump(mode="json"),
                parties=list(parties),
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            self._proposals[proposal.id] = proposal
            return proposal.model_copy(deep=True)

    def decide(
        self, proposal_id: str, org_id: str, decision: DecisionType, comment: str | None
    ) -> Proposal:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise ProposalNotFound(proposal_id)
            if org_id not in proposal.parties:
                raise ProposalForbidden("Only the two parties can decide on this proposal")
            if proposal.status in FINAL_STATUSES:
                raise ProposalConflict(f"Proposal is already {proposal.status.value}")
            if any(d.org_id == org_id for d in proposal.decisions):
                raise ProposalConflict("This organization has already decided")
            now = datetime.now(timezone.utc)
            decisions = [
                *proposal.decisions,
                Decision(org_id=org_id, decision=decision, comment=comment, decided_at=now),
            ]
            updated = proposal.model_copy(
                update={
                    "decisions": decisions,
                    "status": next_status(proposal.parties, decisions),
                    "version": proposal.version + 1,
                    "updated_at": now,
                }
            )
            self._proposals[proposal_id] = updated
            return updated.model_copy(deep=True)

    def get(self, proposal_id: str) -> Proposal | None:
        with self._lock:
            p = self._proposals.get(proposal_id)
            return None if p is None else p.model_copy(deep=True)

    def list_for(self, org_id: str) -> list[Proposal]:
        with self._lock:
            return [p.model_copy(deep=True) for p in self._proposals.values() if org_id in p.parties]

    def clear(self) -> None:
        with self._lock:
            self._proposals.clear()
            self._ids = itertools.count(1)
