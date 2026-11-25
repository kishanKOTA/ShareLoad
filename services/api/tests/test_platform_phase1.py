"""Phase 1 contracts and infrastructure. No live Gemini key is required."""
import json
import shutil
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api.v1.fixtures import FixtureError, load_fixtures
from app.config import ROOT, get_config
from app.ingestion.extract import EXTRACT_PROMPT, _to_shipment
from app.main import create_app
from app.models.database import SCHEMA_VERSION, initialize_database
from app.schemas import Organization, Shipment, Trip, Vehicle

DEMO = ROOT / "data/demo"


@pytest.fixture
def demo(tmp_path):
    return shutil.copytree(DEMO, tmp_path / "demo")


@pytest.fixture
def client(demo, tmp_path):
    with TestClient(create_app(data_dir=demo, database_path=tmp_path / "phase1.db",
                               use_gemini=False)) as client:
        yield client


@pytest.mark.parametrize("resource,schema,org", [
    ("vehicles", Vehicle, "northstar"), ("trips", Trip, "northstar"),
    ("shipments", Shipment, "lakeview"),
])
def test_reads_follow_contract_and_ownership(client, resource, schema, org):
    response = client.get(f"/api/v1/organizations/{org}/{resource}", headers={"X-Org-Id": org})
    assert response.status_code == 200
    records = [schema.model_validate(r) for r in response.json()]
    assert records and all(r.org_id == org for r in records)
    assert client.get(f"/api/v1/organizations/{org}/{resource}",
                      headers={"X-Org-Id": "other"}).status_code == 403
    assert client.get(f"/api/v1/organizations/{org}/{resource}",
                      headers={"X-Org-Id": " "}).status_code == 400
    assert client.get(f"/api/v1/organizations/{org}/{resource}").status_code == 422
    assert client.get(f"/api/v1/organizations/unknown/{resource}",
                      headers={"X-Org-Id": org}).status_code == 404


def test_organizations_and_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert len([Organization.model_validate(o) for o in
                client.get("/api/v1/organizations").json()]) == 2
    assert client.get("/api/v1/organizations/lakeview/vehicles",
                      headers={"X-Org-Id": "lakeview"}).json() == []


@pytest.mark.parametrize("filename,mutation", [
    ("vehicles", lambda rows: rows[0].update(payload_kg=-1)),
    ("vehicles", lambda rows: rows.append(rows[0].copy())),
    ("shipments", lambda rows: rows[0].update(org_id="other")),
    ("trips", lambda rows: rows[0].update(vehicle_id="missing")),
    ("trips", lambda rows: rows[0].update(org_id="lakeview")),
    ("trips", lambda rows: rows[0]["depart_window"].update(start="2026-11-20T06:00:00")),
])
def test_fixture_errors_fail_startup(demo, tmp_path, filename, mutation):
    path = demo / f"{filename}.json"
    rows = json.loads(path.read_text())
    mutation(rows)
    path.write_text(json.dumps(rows))
    with pytest.raises(FixtureError):
        with TestClient(create_app(data_dir=demo, database_path=tmp_path / "invalid.db")):
            pass


def test_invalid_json_is_clear_error_without_lifespan(demo):
    (demo / "shipments.json").write_text("{")
    client = TestClient(create_app(data_dir=demo, use_gemini=False))
    response = client.get("/api/v1/organizations")
    assert response.status_code == 500
    assert response.json()["code"] == "FIXTURE_VALIDATION_ERROR"


def test_database_idempotent_and_preserves_existing_rows(tmp_path):
    path = tmp_path / "nested" / "test.db"
    initialize_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"proposals", "proposal_decisions", "audit_events", "audit_visibility", "runtime_state"}
        assert all(connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0 for t in tables - {"runtime_state"})
        connection.execute("INSERT INTO audit_events VALUES ('e',NULL,'agent','test','test','{}','2026-11-20T00:00:00Z')")
    initialize_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="newer"):
        initialize_database(path)


def test_startup_initializes_database(client):
    with sqlite3.connect(client.app.state.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_environment_config_and_cors(monkeypatch, demo, tmp_path):
    monkeypatch.setenv("CORS_ORIGINS", "https://frontend.example")
    monkeypatch.setenv("SHARELOAD_DATA_DIR", str(demo))
    monkeypatch.setenv("SHARELOAD_DATABASE_PATH", str(tmp_path / "env.db"))
    settings = get_config()
    assert settings.data_dir == demo
    assert settings.database_path == tmp_path / "env.db"
    with TestClient(create_app(use_gemini=False)) as client:
        for origin, status in [("https://frontend.example", 200), ("https://other.example", 400)]:
            r = client.options("/health", headers={"Origin": origin,
                               "Access-Control-Request-Method": "GET",
                               "Access-Control-Request-Headers": "X-Org-Id"})
            assert r.status_code == status
        r = client.options("/health", headers={"Origin": "https://frontend.example",
                           "Access-Control-Request-Method": "DELETE"})
        assert r.status_code == 400
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        get_config()


def mock_provider(monkeypatch, reply):
    calls = []
    def generate_content(**kwargs):
        calls.append(kwargs)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=json.dumps(reply))
    monkeypatch.setattr(main, "get_gemini_client", lambda: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)))
    return calls


@pytest.mark.parametrize("strict,status", [(False, 200), (True, 422)])
def test_missing_critical_fields_have_explicit_errors(demo, tmp_path, monkeypatch, strict, status):
    calls = mock_provider(monkeypatch, {"confidence": 0.4})
    with TestClient(create_app(data_dir=demo, database_path=tmp_path / "test.db")) as client:
        response = client.post("/api/v1/ingest/shipments/parse",
                               params={"require_complete": strict},
                               headers={"X-Org-Id": "lakeview"}, json={"raw_text": "Need freight"})
    assert response.status_code == status
    body = response.json()
    if strict:
        assert body["code"] == "MISSING_CRITICAL_FIELD"
        assert "origin" in body["missing_fields"]
        shipment = Shipment.model_validate(body["shipment"])
        assert "manually" in body["detail"]
    else:
        shipment = Shipment.model_validate(body)
        assert response.headers["X-Manual-Entry-Required"] == "true"
        assert json.loads(response.headers["X-Shipment-Validation-Errors"])[0]["field"] == "origin"
    assert shipment.origin is None and shipment.weight_kg is None
    assert len(calls) == 1


def test_provider_error_is_redacted(demo, tmp_path, monkeypatch):
    calls = mock_provider(monkeypatch, RuntimeError("secret-key=do-not-leak private shipment text"))
    with TestClient(create_app(data_dir=demo, database_path=tmp_path / "test.db")) as client:
        response = client.post("/api/v1/ingest/shipments/parse", headers={"X-Org-Id": "lakeview"},
                               json={"raw_text": "test"})
    assert response.status_code == 502
    assert "do-not-leak" not in response.text
    assert "manually" in response.json()["detail"]
    assert len(calls) == 1


def test_blank_text_and_foreign_org_do_not_call_provider(client):
    for body in ({"raw_text": "   "}, {"raw_text": "x" * 20001}, {"raw_text": "x", "org_id": "northstar"}):
        assert client.post("/api/v1/ingest/shipments/parse", headers={"X-Org-Id": "lakeview"},
                           json=body).status_code == 422
    assert client.post("/api/v1/ingest/shipments/parse", headers={"X-Org-Id": " "},
                       json={"raw_text": "test"}).status_code == 400


def test_uncertain_fields_cleared_and_temperature_missing_flagged():
    shipment = _to_shipment(json.dumps({"confidence": 0.5, "weight_kg": 1200,
                                       "cargo_type": "refrigerated", "missing_fields": ["weight_kg"]}),
                            "raw", "lakeview", "s")
    assert shipment.weight_kg is None
    assert {"weight_kg", "temp_min_c", "temp_max_c"} <= set(shipment.extraction.missing_fields)
    assert "approximate coordinates" in EXTRACT_PROMPT


def test_provider_client_has_timeout_and_no_hidden_retries(monkeypatch):
    from google import genai
    from app.ingestion import provider
    captured = {}
    def fake_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()
    monkeypatch.setattr(genai, "Client", fake_client)
    monkeypatch.setattr(provider, "get_config", lambda: SimpleNamespace(
        gemini_api_key="test-key-not-real", gemini_timeout_ms=1234))
    provider.get_gemini_client()
    assert captured["http_options"].timeout == 1234
    assert captured["http_options"].retry_options.attempts == 1


def test_provider_initialization_failure_is_safe(demo, tmp_path, monkeypatch):
    def broken_client():
        raise RuntimeError("secret-value")
    monkeypatch.setattr(main, "get_gemini_client", broken_client)
    with TestClient(create_app(data_dir=demo, database_path=tmp_path / "test.db")) as client:
        response = client.post("/api/v1/ingest/shipments/parse", headers={"X-Org-Id": "lakeview"},
                               json={"raw_text": "test"})
    assert response.status_code == 502
    assert "secret-value" not in response.text
