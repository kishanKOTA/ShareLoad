"""Proposal, audit and demo-reset API tests. Gemini is disabled; no network calls."""

import shutil

import pytest
from fastapi.testclient import TestClient

from app.agent.agent import CACHE_FILENAME
from app.main import create_app
from app.matching.scan import DEMO_DIR, clear_scan_cache
from app.proposals.store import next_status
from app.schemas import Decision, DecisionType, ProposalStatus

MATCH = "opp-trip-a-return-ship-b"
REEFER = "opp-trip-a-return-ship-b-reefer"
NORTH = {"X-Org-Id": "northstar"}   # trip owner
LAKE = {"X-Org-Id": "lakeview"}     # shipment owner


@pytest.fixture
def client(tmp_path):
    shutil.copytree(DEMO_DIR, tmp_path / "demo")
    (tmp_path / "demo" / CACHE_FILENAME).unlink(missing_ok=True)
    yield TestClient(create_app(data_dir=tmp_path / "demo", use_gemini=False))
    clear_scan_cache()


def propose(client, headers=NORTH, opp=MATCH):
    return client.post(f"/api/v1/opportunities/{opp}/proposals", headers=headers)


def decide(client, proposal_id, headers, decision, comment=None):
    return client.post(
        f"/api/v1/proposals/{proposal_id}/decision",
        headers=headers,
        json={"decision": decision, "comment": comment},
    )


# --------------------------------------------------------------------------- #
# Creating proposals
# --------------------------------------------------------------------------- #


def test_create_proposal(client):
    r = propose(client)
    assert r.status_code == 201
    p = r.json()
    assert p["opportunity_id"] == MATCH
    assert p["status"] == "pending_approvals"
    assert p["version"] == 1
    assert p["decisions"] == []
    assert sorted(p["parties"]) == ["lakeview", "northstar"]
    assert p["created_by"] == "northstar"
    assert p["snapshot"]["id"] == MATCH
    assert p["snapshot"]["impact"] is not None


def test_snapshot_carries_explanation_after_scan(client):
    client.post("/api/v1/opportunities/scan")
    assert propose(client).json()["snapshot"]["explanation"]


def test_shipment_owner_can_propose(client):
    assert propose(client, headers=LAKE).status_code == 201


def test_cannot_propose_rejected_opportunity(client):
    assert propose(client, opp=REEFER).status_code == 409


def test_cannot_propose_unknown_opportunity(client):
    assert propose(client, opp="opp-nope").status_code == 404


def test_duplicate_open_proposal_is_conflict(client):
    propose(client)
    assert propose(client, headers=LAKE).status_code == 409


def test_can_repropose_after_rejection(client):
    pid = propose(client).json()["id"]
    decide(client, pid, LAKE, "reject")
    assert propose(client).status_code == 201


def test_proposal_routes_need_known_org(client):
    assert propose(client, headers={}).status_code == 422
    assert propose(client, headers={"X-Org-Id": "nobody"}).status_code == 403
    assert client.get("/api/v1/proposals").status_code == 422
    assert client.get("/api/v1/audit-events", headers={"X-Org-Id": "nobody"}).status_code == 403


# --------------------------------------------------------------------------- #
# Decisions and status transitions
# --------------------------------------------------------------------------- #


def test_one_approval_is_partial(client):
    pid = propose(client).json()["id"]
    r = decide(client, pid, NORTH, "approve", "Truck is free")
    assert r.status_code == 200
    p = r.json()
    assert p["status"] == "partially_approved"
    assert p["version"] == 2
    assert p["decisions"][0]["org_id"] == "northstar"
    assert p["decisions"][0]["comment"] == "Truck is free"


def test_both_approve(client):
    pid = propose(client).json()["id"]
    decide(client, pid, NORTH, "approve")
    p = decide(client, pid, LAKE, "approve").json()
    assert p["status"] == "approved_for_external_coordination"
    assert p["version"] == 3
    assert {d["org_id"] for d in p["decisions"]} == {"northstar", "lakeview"}


@pytest.mark.parametrize("first, second", [
    ((NORTH, "reject"), None),
    ((LAKE, "reject"), None),
    ((NORTH, "approve"), (LAKE, "reject")),
    ((LAKE, "approve"), (NORTH, "reject")),
])
def test_any_reject_rejects(client, first, second):
    pid = propose(client).json()["id"]
    p = decide(client, pid, *first).json()
    if second:
        p = decide(client, pid, *second).json()
    assert p["status"] == "rejected"


def test_final_proposals_cannot_change(client):
    pid = propose(client).json()["id"]
    decide(client, pid, NORTH, "reject")
    assert decide(client, pid, LAKE, "approve").status_code == 409

    client.post("/api/v1/demo/reset")
    pid = propose(client).json()["id"]
    decide(client, pid, NORTH, "approve")
    decide(client, pid, LAKE, "approve")
    assert decide(client, pid, LAKE, "reject").status_code == 409


def test_org_cannot_decide_twice(client):
    pid = propose(client).json()["id"]
    decide(client, pid, NORTH, "approve")
    r = decide(client, pid, NORTH, "approve")
    assert r.status_code == 409
    assert client.get("/api/v1/proposals", headers=NORTH).json()[0]["version"] == 2


def test_decision_on_unknown_proposal_is_404(client):
    assert decide(client, "prop-999", NORTH, "approve").status_code == 404


def test_invalid_decision_value_is_422(client):
    pid = propose(client).json()["id"]
    assert decide(client, pid, NORTH, "maybe").status_code == 422


def test_next_status_rules():
    def d(org, kind):
        return Decision(org_id=org, decision=DecisionType(kind), decided_at="2026-11-20T09:00:00Z")

    parties = ["a", "b"]
    assert next_status(parties, []) == ProposalStatus.PENDING_APPROVALS
    assert next_status(parties, [d("a", "approve")]) == ProposalStatus.PARTIALLY_APPROVED
    assert next_status(parties, [d("a", "approve"), d("b", "approve")]) == (
        ProposalStatus.APPROVED_FOR_EXTERNAL_COORDINATION
    )
    assert next_status(parties, [d("b", "reject")]) == ProposalStatus.REJECTED


# --------------------------------------------------------------------------- #
# Org scoping
# --------------------------------------------------------------------------- #


def test_both_parties_see_proposal(client):
    pid = propose(client).json()["id"]
    for headers in (NORTH, LAKE):
        assert [p["id"] for p in client.get("/api/v1/proposals", headers=headers).json()] == [pid]


def test_non_party_cannot_see_or_decide(client, tmp_path):
    # Add a third org that is not part of the match.
    import json
    orgs_path = tmp_path / "demo" / "organizations.json"
    orgs = json.loads(orgs_path.read_text())
    orgs.append({"id": "outsider", "name": "Outsider Co.", "region": "Elsewhere"})
    orgs_path.write_text(json.dumps(orgs))
    outsider = {"X-Org-Id": "outsider"}

    pid = propose(client).json()["id"]
    assert propose(client, headers=outsider).status_code in (403, 409)
    assert client.get("/api/v1/proposals", headers=outsider).json() == []
    assert decide(client, pid, outsider, "approve").status_code == 403
    events = client.get("/api/v1/audit-events", headers=outsider).json()
    assert not [e for e in events if e["event_type"].startswith("proposal.")]


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #


def test_audit_trail_for_full_flow(client):
    client.post("/api/v1/opportunities/scan")
    pid = propose(client).json()["id"]
    decide(client, pid, NORTH, "approve", "ok")
    decide(client, pid, LAKE, "approve")

    events = client.get("/api/v1/audit-events", headers=LAKE).json()
    assert [e["event_type"] for e in events] == [
        "scan.completed", "proposal.created", "proposal.approved", "proposal.approved",
    ]
    scan, created, first, second = events
    assert scan["actor"] == "agent" and scan["org_id"] is None
    assert scan["payload"]["tool_calls"]
    assert scan["payload"]["opportunity_ids"] == [MATCH]
    assert created["actor"] == "user" and created["org_id"] == "northstar"
    assert created["entity"] == f"proposal:{pid}"
    assert first["payload"]["comment"] == "ok"
    assert first["payload"]["status"] == "partially_approved"
    assert second["org_id"] == "lakeview"
    assert second["payload"]["status"] == "approved_for_external_coordination"
    assert len({e["id"] for e in events}) == 4


def test_reject_is_audited(client):
    pid = propose(client).json()["id"]
    decide(client, pid, LAKE, "reject", "No dock slot")
    last = client.get("/api/v1/audit-events", headers=NORTH).json()[-1]
    assert last["event_type"] == "proposal.rejected"
    assert last["payload"] == {
        "decision": "reject", "comment": "No dock slot", "status": "rejected", "version": 2,
    }


# --------------------------------------------------------------------------- #
# Demo reset
# --------------------------------------------------------------------------- #


def test_demo_reset_clears_state(client):
    client.post("/api/v1/opportunities/scan")
    pid = propose(client).json()["id"]
    decide(client, pid, NORTH, "approve")

    r = client.post("/api/v1/demo/reset")
    assert r.status_code == 200
    assert r.json() == {"status": "reset"}
    assert client.get("/api/v1/proposals", headers=NORTH).json() == []
    assert client.get("/api/v1/audit-events", headers=NORTH).json() == []
    # Last scan is gone, so the opportunity is served without the agent's explanation.
    assert client.get(f"/api/v1/opportunities/{MATCH}").json()["explanation"] is None
    # Ids start over and the same opportunity can be proposed again.
    assert propose(client).json()["id"] == "prop-1"
