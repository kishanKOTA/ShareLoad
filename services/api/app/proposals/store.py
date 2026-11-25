"""SQLite proposals. Decisions and audit writes commit in one transaction."""
from datetime import datetime, timezone
import json
import sqlite3
from uuid import uuid4

from app.audit import AuditLog
from app.models.database import Database
from app.schemas import Actor, Decision, DecisionType, Opportunity, Proposal, ProposalStatus

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
    def __init__(self, database: Database, audit: AuditLog):
        self.database = database
        self.audit = audit

    @staticmethod
    def _read(connection, row) -> Proposal:
        decisions = connection.execute(
            "SELECT * FROM proposal_decisions WHERE proposal_id=? ORDER BY rowid", (row["id"],)
        ).fetchall()
        snapshot = Opportunity.model_validate_json(row["snapshot_json"])
        return Proposal(
            id=row["id"], opportunity_id=row["opportunity_id"], status=row["status"],
            version=row["version"], snapshot=snapshot.model_dump(mode="json"),
            parties=json.loads(row["parties_json"]), created_by=row["created_by"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            decisions=[Decision(org_id=d["org_id"], decision=d["decision"],
                                comment=d["comment"], decided_at=d["decided_at"]) for d in decisions],
        )

    def create(self, opportunity: Opportunity, parties: list[str], created_by: str,
               generation: int) -> Proposal:
        if len(set(parties)) != 2 or created_by not in parties:
            raise ProposalForbidden("Only the two distinct trip and shipment owners can propose")
        if (not opportunity.feasible or opportunity.reason_codes or not opportunity.checks
                or any(not check.passed for check in opportunity.checks)
                or opportunity.baseline is None or opportunity.shared is None
                or not opportunity.baseline.geometry or not opportunity.shared.geometry
                or opportunity.impact is None or not opportunity.impact.formula_trace):
            raise ProposalConflict("Only feasible opportunities with complete route and impact evidence can be proposed")
        now = datetime.now(timezone.utc)
        proposal = Proposal(id=f"prop-{uuid4().hex}", opportunity_id=opportunity.id,
                            status=ProposalStatus.PENDING_APPROVALS, version=1,
                            snapshot=opportunity.model_dump(mode="json"), parties=list(parties),
                            created_by=created_by, created_at=now, updated_at=now)
        try:
            with self.database.transaction(write=True) as connection:
                current = connection.execute("SELECT generation FROM runtime_state WHERE id=1").fetchone()[0]
                if current != generation:
                    raise ProposalConflict("Demo was reset; reload the opportunity before proposing")
                connection.execute("INSERT INTO proposals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                    proposal.id, proposal.opportunity_id, proposal.status.value, proposal.version,
                    opportunity.model_dump_json(), json.dumps(parties), created_by,
                    now.isoformat(), now.isoformat(),
                ))
                self.audit.record(connection=connection, actor=Actor.USER, org_id=created_by,
                                  event_type="proposal.created", entity=f"proposal:{proposal.id}",
                                  payload={"opportunity_id": opportunity.id, "status": proposal.status.value},
                                  visible_to=parties)
        except sqlite3.IntegrityError as exc:
            if "proposals.opportunity_id" in str(exc):
                raise ProposalConflict("Opportunity already has an active or approved proposal") from exc
            raise
        return proposal

    def decide(self, proposal_id: str, org_id: str, decision: DecisionType,
               comment: str | None) -> Proposal:
        # BEGIN IMMEDIATE ensures two approvals cannot both read version 1.
        with self.database.transaction(write=True) as connection:
            row = connection.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None:
                raise ProposalNotFound(proposal_id)
            proposal = self._read(connection, row)
            if org_id not in proposal.parties:
                raise ProposalForbidden("Only the two parties can decide on this proposal")
            if proposal.status not in {ProposalStatus.PENDING_APPROVALS, ProposalStatus.PARTIALLY_APPROVED}:
                raise ProposalConflict(f"Proposal is already {proposal.status.value}")
            if any(d.org_id == org_id for d in proposal.decisions):
                raise ProposalConflict("This organization has already decided")
            now = datetime.now(timezone.utc)
            recorded = Decision(org_id=org_id, decision=decision, comment=comment, decided_at=now)
            status = next_status(proposal.parties, [*proposal.decisions, recorded])
            connection.execute("INSERT INTO proposal_decisions VALUES (?, ?, ?, ?, ?)", (
                proposal_id, org_id, decision.value, comment, now.isoformat(),
            ))
            connection.execute("UPDATE proposals SET status=?, version=version+1, updated_at=? WHERE id=?", (
                status.value, now.isoformat(), proposal_id,
            ))
            self.audit.record(connection=connection, actor=Actor.USER, org_id=org_id,
                              event_type="proposal.approved" if decision == DecisionType.APPROVE else "proposal.rejected",
                              entity=f"proposal:{proposal_id}", visible_to=proposal.parties,
                              payload={"decision": decision.value, "comment": comment,
                                       "status": status.value, "version": proposal.version + 1})
            return self._read(connection, connection.execute(
                "SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone())

    def list_for(self, org_id: str) -> list[Proposal]:
        with self.database.transaction() as connection:
            rows = connection.execute("""SELECT p.* FROM proposals p
                WHERE EXISTS (SELECT 1 FROM json_each(p.parties_json) WHERE value=?)
                ORDER BY p.rowid""", (org_id,)).fetchall()
            return [self._read(connection, row) for row in rows]
