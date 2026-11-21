"""SQLite workflow, concurrency, privacy and actual deterministic engine tests."""
import json
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent.agent import CACHE_FILENAME, run_agent_scan
from app.config import ROOT, get_config
from app.matching.scan import get_opportunity
from app.models.database import MIGRATIONS, SCHEMA_VERSION, initialize_database
from app.schemas import AuditEvent, Opportunity, Proposal

MATCH = "opp-trip-a-return-ship-b"
NORTH, LAKE, OUT = ({"X-Org-Id": org} for org in ("northstar", "lakeview", "outsider"))
BASE = "/api/v1"


@pytest.fixture
def setup(tmp_path):
    demo = shutil.copytree(ROOT / "data/demo", tmp_path / "demo")
    orgs = json.loads((demo / "organizations.json").read_text())
    orgs.append({"id": "outsider", "name": "Third Company", "region": "Elsewhere"})
    (demo / "organizations.json").write_text(json.dumps(orgs))
    return dict(data_dir=demo, database_path=tmp_path / "state.db", use_gemini=False, demo_mode=True)


@pytest.fixture
def client(setup):
    with TestClient(main.create_app(**setup)) as client:
        yield client


def propose(client, headers=NORTH, opportunity=MATCH):
    return client.post(f"{BASE}/opportunities/{opportunity}/proposals", headers=headers)


def decide(client, pid, headers, value="approve"):
    return client.post(f"{BASE}/proposals/{pid}/decision", headers=headers,
                       json={"decision": value, "comment": "reviewed"})


def audit(client, headers=NORTH):
    response = client.get(f"{BASE}/audit-events", headers=headers)
    assert response.status_code == 200
    return [AuditEvent.model_validate(e) for e in response.json()]


def test_real_engine_output_and_scope(client):
    response = client.post(f"{BASE}/opportunities/scan", headers=NORTH)
    assert response.status_code == 200
    body = response.json()
    expected = run_agent_scan(client.app.state.engine.data_dir, use_gemini=False)
    assert body["mode"] == "template" and body["candidates_considered"] == 3
    for key in ("opportunities", "rejected"):
        assert body[key] == [o.model_dump(mode="json") for o in getattr(expected, key)]
    assert {c for o in body["rejected"] for c in o["reason_codes"]} == {
        "CARGO_TEMP_UNSUPPORTED", "TIME_WINDOW_CONFLICT"}
    detail = client.get(f"{BASE}/opportunities/{MATCH}", headers=LAKE).json()
    assert detail == body["opportunities"][0]
    assert detail["baseline"]["geometry"]["features"] and detail["impact"]["formula_trace"]
    assert client.get(f"{BASE}/opportunities/{MATCH}", headers=OUT).status_code == 403
    assert client.post(f"{BASE}/opportunities/scan").status_code == 422
    assert client.get(f"{BASE}/opportunities/{MATCH}").status_code == 422
    assert client.post(f"{BASE}/opportunities/scan", headers=OUT).json()["opportunities"] == []
    assert audit(client, OUT) == []


def test_subset_suppresses_global_summary_and_private_tools(setup):
    demo = setup["data_dir"]
    def append(name, record):
        path = demo / f"{name}.json"
        rows = json.loads(path.read_text())
        rows.append(record(rows))
        path.write_text(json.dumps(rows))
    append("organizations", lambda rows: {"id": "fourth", "name": "Fourth", "region": "Elsewhere"})
    append("vehicles", lambda rows: rows[0] | {"id": "private-vehicle", "org_id": "outsider"})
    append("trips", lambda rows: rows[1] | {"id": "private-trip", "org_id": "outsider", "vehicle_id": "private-vehicle"})
    append("shipments", lambda rows: rows[0] | {"id": "private-shipment", "org_id": "fourth"})
    with TestClient(main.create_app(**setup)) as client:
        result = client.post(f"{BASE}/opportunities/scan", headers=NORTH).json()
        assert result["agent_summary"] == ""
        assert "private-trip" not in json.dumps(result)
        assert "private-trip" not in json.dumps([e.model_dump(mode="json") for e in audit(client)])


def test_snapshot_workflow_persists_across_restart(setup):
    with TestClient(main.create_app(**setup)) as client:
        client.post(f"{BASE}/opportunities/scan", headers=NORTH)
        proposal = Proposal.model_validate(propose(client).json())
        assert decide(client, proposal.id, LAKE).json()["status"] == "partially_approved"
    with TestClient(main.create_app(**setup)) as client:
        stored = client.get(f"{BASE}/proposals", headers=NORTH).json()[0]
        assert stored["snapshot"] == proposal.snapshot and stored["version"] == 2
        final = decide(client, proposal.id, NORTH).json()
        assert final["status"] == "approved_for_external_coordination" and final["version"] == 3
        assert final["snapshot"] == proposal.snapshot and len(final["decisions"]) == 2
        assert propose(client).status_code == 409
        assert decide(client, proposal.id, NORTH, "reject").status_code == 409
        assert [e.event_type for e in audit(client)] == [
            "scan.completed", "proposal.created", "proposal.approved", "proposal.approved"]
        assert client.get(f"{BASE}/proposals", headers=OUT).json() == []
        assert audit(client, OUT) == []
        assert decide(client, proposal.id, OUT).status_code == 403


@pytest.mark.parametrize("first,second", [(NORTH, LAKE), (LAKE, NORTH)])
def test_rejection_final_and_new_reproposal(client, first, second):
    pid = propose(client).json()["id"]
    assert decide(client, pid, first).json()["status"] == "partially_approved"
    assert decide(client, pid, second, "reject").json()["status"] == "rejected"
    assert decide(client, pid, first).status_code == 409
    assert propose(client).json()["id"] != pid


def test_duplicate_decision_no_extra_audit(client):
    pid = propose(client).json()["id"]
    assert decide(client, pid, NORTH).status_code == 200
    for choice in ("approve", "reject"):
        assert decide(client, pid, NORTH, choice).status_code == 409
    assert len(audit(client)) == 2


@pytest.mark.parametrize("operation", ["both", "same", "create"])
def test_concurrent_requests_across_app_instances(setup, operation):
    with ExitStack() as stack:
        clients = [stack.enter_context(TestClient(main.create_app(**setup))) for _ in range(2)]
        pid = propose(clients[0]).json()["id"] if operation != "create" else None
        barrier = threading.Barrier(2)
        def submit(i):
            barrier.wait(timeout=5)
            return propose(clients[i]) if pid is None else decide(
                clients[i], pid, NORTH if i == 0 or operation == "same" else LAKE)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        expected = {"both": [200, 200], "same": [200, 409], "create": [201, 409]}[operation]
        assert sorted(r.status_code for r in results) == expected
        proposal = clients[0].get(f"{BASE}/proposals", headers=LAKE).json()[0]
        assert proposal["version"] == {"both": 3, "same": 2, "create": 1}[operation]
        assert len(audit(clients[0])) == proposal["version"]
        if operation == "both":
            assert proposal["status"] == "approved_for_external_coordination"


@pytest.mark.parametrize("operation", ["create", "decide"])
def test_audit_failure_rolls_back_workflow(client, monkeypatch, operation):
    pid = propose(client).json()["id"] if operation == "decide" else None
    def fail(**kwargs):
        raise sqlite3.OperationalError("private write failure")
    monkeypatch.setattr(client.app.state.audit, "record", fail)
    response = decide(client, pid, NORTH) if pid else propose(client)
    assert response.status_code == 503 and "private write failure" not in response.text
    stored = client.get(f"{BASE}/proposals", headers=NORTH).json()
    assert (stored[0]["version"] == 1 and stored[0]["decisions"] == []) if pid else stored == []


def test_snapshot_immutable_in_database(client):
    pid = propose(client).json()["id"]
    with sqlite3.connect(client.app.state.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE proposals SET snapshot_json='{}' WHERE id=?", (pid,))


def test_incomplete_evidence_not_proposable(client, monkeypatch):
    opportunity = get_opportunity(MATCH, client.app.state.engine.data_dir)
    opportunity.impact = None
    monkeypatch.setattr(main, "get_opportunity", lambda *args: opportunity)
    assert propose(client).status_code == 409
    assert audit(client) == []


def test_engine_failure_explicit_and_redacted(client, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("secret-key")
    monkeypatch.setattr(main, "run_agent_scan", fail)
    response = client.post(f"{BASE}/opportunities/scan", headers=NORTH)
    assert response.status_code == 502 and "secret-key" not in response.text
    assert audit(client) == []


def test_mocked_agent_output_preserved_and_failure_reason_redacted(client, monkeypatch):
    expected = run_agent_scan(client.app.state.engine.data_dir, use_gemini=False)
    expected.mode = "gemini"
    expected.fallback_reason = "provider failure secret-key"
    monkeypatch.setattr(main, "run_agent_scan", lambda **kwargs: expected.model_copy(deep=True))
    response = client.post(f"{BASE}/opportunities/scan", headers=NORTH)
    assert response.json()["agent_summary"] == expected.agent_summary
    assert response.json()["opportunities"] == [o.model_dump(mode="json") for o in expected.opportunities]
    assert "secret-key" not in response.text


def test_reset_guard_and_production_config(setup, monkeypatch):
    setup["demo_mode"] = False
    with TestClient(main.create_app(**setup)) as client:
        assert client.post(f"{BASE}/demo/reset").status_code == 403
    monkeypatch.setenv("SHARELOAD_ENV", "production")
    monkeypatch.setenv("SHARELOAD_DEMO_MODE", "true")
    with pytest.raises(ValueError, match="production"):
        get_config()
    monkeypatch.setenv("SHARELOAD_DEMO_MODE", "false")
    setup["demo_mode"] = True
    with pytest.raises(ValueError, match="production"):
        main.create_app(**setup)


def test_reset_restores_seed_keeps_source_and_does_not_reuse_ids(client, setup):
    source = setup["data_dir"]
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    client.post(f"{BASE}/opportunities/scan", headers=NORTH)
    pid = propose(client).json()["id"]
    decide(client, pid, NORTH)
    runtime = client.app.state.engine.data_dir
    (runtime / CACHE_FILENAME).write_text("bad cache")
    (runtime / "shipments.json").write_text("[]")
    assert client.post(f"{BASE}/demo/reset").json() == {"status": "reset"}
    assert client.get(f"{BASE}/proposals", headers=NORTH).json() == []
    assert [e.event_type for e in audit(client)] == ["demo.reset"]
    assert client.get(f"{BASE}/opportunities/{MATCH}", headers=NORTH).json()["explanation"] is None
    assert (runtime / CACHE_FILENAME).read_bytes() == (source / CACHE_FILENAME).read_bytes()
    assert (runtime / "shipments.json").read_bytes() == (source / "shipments.json").read_bytes()
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original
    assert propose(client).json()["id"] != pid
    assert decide(client, pid, LAKE).status_code == 404


def test_reset_generation_blocks_stale_create(client):
    from app.proposals import ProposalConflict
    opportunity = Opportunity.model_validate(client.get(f"{BASE}/opportunities/{MATCH}", headers=NORTH).json())
    client.post(f"{BASE}/demo/reset")
    with pytest.raises(ProposalConflict, match="reset"):
        client.app.state.proposals.create(opportunity, ["northstar", "lakeview"], "northstar", generation=0)


def test_migrate_phase1_database_keeps_rows(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        for statement in MIGRATIONS[1]:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")
        connection.execute("INSERT INTO audit_events VALUES ('original',NULL,'agent','old','scan','{}','2026-11-20T00:00:00Z')")
        connection.execute("INSERT INTO audit_visibility VALUES ('original','northstar')")
    initialize_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT id FROM audit_events").fetchone()[0] == "original"


def test_health_readiness_and_frontend_preflight(client):
    for path in ("/health", "/ready", f"{BASE}/health", f"{BASE}/ready"):
        assert client.get(path).status_code == 200
    response = client.options(f"{BASE}/proposals/x/decision", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type,X-Org-Id"})
    assert response.status_code == 200


def test_decision_cannot_choose_actor_or_org(client):
    pid = propose(client).json()["id"]
    response = client.post(f"{BASE}/proposals/{pid}/decision", headers=NORTH,
                           json={"decision": "approve", "actor": "agent", "org_id": "lakeview"})
    assert response.status_code == 422 and len(audit(client)) == 1


def test_api_uses_actual_agent_with_mocked_gemini_and_runtime_cache(client, monkeypatch, setup):
    from types import SimpleNamespace
    calls = []
    class Chat:
        def send_message(self, message):
            calls.append(message)
            return SimpleNamespace(function_calls=[SimpleNamespace(name="list_candidates", args={})] if len(calls) == 1 else [])
    fake = SimpleNamespace(
        chats=SimpleNamespace(create=lambda **kwargs: Chat()),
        models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(
            text=json.dumps({"summary": "", "explanations": []}))),
        close=lambda: None,
    )
    before = (setup["data_dir"] / CACHE_FILENAME).read_bytes()
    client.app.state.use_gemini = True
    monkeypatch.setattr(main, "get_gemini_client", lambda: fake)
    response = client.post(f"{BASE}/opportunities/scan", headers=NORTH)
    assert response.status_code == 200 and response.json()["mode"] == "gemini"
    assert response.json()["template_summary"] is True
    assert calls and response.json()["tool_calls"][0]["name"] == "list_candidates"
    assert (setup["data_dir"] / CACHE_FILENAME).read_bytes() == before
    persisted = client.get(f"{BASE}/opportunities/{MATCH}", headers=NORTH).json()
    assert persisted == response.json()["opportunities"][0]


def test_overlong_comment_and_nonparty_create(client):
    pid = propose(client).json()["id"]
    assert propose(client, OUT).status_code == 403
    response = client.post(f"{BASE}/proposals/{pid}/decision", headers=NORTH,
                           json={"decision": "approve", "comment": "x" * 501})
    assert response.status_code == 422
    assert len(audit(client)) == 1
