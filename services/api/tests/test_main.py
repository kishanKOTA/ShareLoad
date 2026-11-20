"""API tests with FastAPI's TestClient. Gemini is disabled; no network calls."""

import shutil

import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app.agent.agent import CACHE_FILENAME
from app.main import create_app
from app.matching.scan import DEMO_DIR, clear_scan_cache

MATCH = "opp-trip-a-return-ship-b"
REEFER = "opp-trip-a-return-ship-b-reefer"


@pytest.fixture
def data_dir(tmp_path):
    shutil.copytree(DEMO_DIR, tmp_path / "demo")
    (tmp_path / "demo" / CACHE_FILENAME).unlink(missing_ok=True)
    yield tmp_path / "demo"
    clear_scan_cache()


@pytest.fixture
def client(data_dir):
    return TestClient(create_app(data_dir=data_dir, use_gemini=False))


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_organizations(client):
    r = client.get("/api/v1/organizations")
    assert r.status_code == 200
    assert {o["id"] for o in r.json()} == {"northstar", "lakeview"}


def test_trips_for_own_org(client):
    r = client.get("/api/v1/organizations/northstar/trips", headers={"X-Org-Id": "northstar"})
    assert r.status_code == 200
    trips = r.json()
    assert trips
    assert all(t["org_id"] == "northstar" for t in trips)
    assert "trip-a-return" in {t["id"] for t in trips}


def test_shipments_for_own_org(client):
    r = client.get("/api/v1/organizations/lakeview/shipments", headers={"X-Org-Id": "lakeview"})
    assert r.status_code == 200
    shipments = r.json()
    assert shipments
    assert all(s["org_id"] == "lakeview" for s in shipments)


def test_org_with_no_records_gets_empty_list(client):
    r = client.get("/api/v1/organizations/lakeview/trips", headers={"X-Org-Id": "lakeview"})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.parametrize("resource", ["trips", "shipments"])
def test_other_orgs_data_is_forbidden(client, resource):
    r = client.get(f"/api/v1/organizations/lakeview/{resource}", headers={"X-Org-Id": "northstar"})
    assert r.status_code == 403


@pytest.mark.parametrize("resource", ["trips", "shipments"])
def test_missing_org_header_is_rejected(client, resource):
    r = client.get(f"/api/v1/organizations/northstar/{resource}")
    assert r.status_code == 422


def test_unknown_org_is_404(client):
    r = client.get("/api/v1/organizations/nobody/trips", headers={"X-Org-Id": "nobody"})
    assert r.status_code == 404


def test_scan_runs_template_mode(client):
    r = client.post("/api/v1/opportunities/scan")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "template"
    assert body["cached"] is False
    assert [o["id"] for o in body["opportunities"]] == [MATCH]
    assert REEFER in {o["id"] for o in body["rejected"]}
    assert body["agent_summary"]
    assert body["tool_calls"]


@pytest.mark.parametrize("query, expected", [("", False), ("?use_cached=true", True),
                                             ("?use_cached=false", False)])
def test_scan_passes_use_cached(client, monkeypatch, query, expected):
    seen = {}
    real = main_mod.run_agent_scan

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(main_mod, "run_agent_scan", spy)
    assert client.post(f"/api/v1/opportunities/scan{query}").status_code == 200
    assert seen["use_cached"] is expected
    assert seen["use_gemini"] is False


def test_get_opportunity_before_scan(client):
    r = client.get(f"/api/v1/opportunities/{MATCH}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == MATCH
    assert body["feasible"] is True
    assert body["explanation"] is None


def test_get_opportunity_after_scan_has_explanation(client):
    client.post("/api/v1/opportunities/scan")
    for opp_id in (MATCH, REEFER):
        r = client.get(f"/api/v1/opportunities/{opp_id}")
        assert r.status_code == 200
        assert r.json()["explanation"]


def test_get_unknown_opportunity_is_404(client):
    assert client.get("/api/v1/opportunities/opp-nope").status_code == 404


def test_cors_allows_frontend_origin(client):
    r = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_other_origin(client):
    r = client.get("/api/v1/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
