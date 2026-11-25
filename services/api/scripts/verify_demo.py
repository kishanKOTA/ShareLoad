"""Exercise a running demo API over HTTP. Explicit --reset authorizes demo writes."""
import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def verify(base_url: str):
    def call(method, path, org=None, body=None, expected=200):
        headers = {"Accept": "application/json"}
        if org:
            headers["X-Org-Id"] = org
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(base_url.rstrip("/") + path, method=method, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            response = urlopen(request, timeout=180)
        except HTTPError as error:
            response = error
        with response:
            payload = json.load(response)
            assert response.status == expected, (path, response.status, payload)
            return payload

    api = "/api/v1"
    assert call("GET", "/health") == {"status": "ok"}
    assert call("GET", "/ready") == {"status": "ready"}
    assert {o["id"] for o in call("GET", api + "/organizations")} >= {"northstar", "lakeview"}
    call("POST", api + "/demo/reset")
    for org, resource in (("northstar", "vehicles"), ("northstar", "trips"), ("lakeview", "shipments")):
        assert call("GET", f"{api}/organizations/{org}/{resource}", org)
    call("GET", api + "/organizations/lakeview/shipments", "northstar", expected=403)
    result = call("POST", api + "/opportunities/scan?use_cached=false", "northstar")
    assert result["candidates_considered"] == 3 and len(result["opportunities"]) == 1
    assert {c for o in result["rejected"] for c in o["reason_codes"]} == {
        "CARGO_TEMP_UNSUPPORTED", "TIME_WINDOW_CONFLICT"}
    opportunity = result["opportunities"][0]
    oid = opportunity["id"]
    detail = call("GET", f"{api}/opportunities/{oid}", "lakeview")
    assert detail == opportunity
    assert detail["baseline"]["geometry"]["features"] and detail["impact"]["formula_trace"]
    proposal = call("POST", f"{api}/opportunities/{oid}/proposals", "northstar", expected=201)
    pid = proposal["id"]
    assert proposal["snapshot"] == detail and proposal["status"] == "pending_approvals"
    call("POST", f"{api}/opportunities/{oid}/proposals", "lakeview", expected=409)
    partial = call("POST", f"{api}/proposals/{pid}/decision", "northstar", {"decision": "approve", "comment": "Truck reviewed"})
    assert partial["status"] == "partially_approved" and partial["version"] == 2
    call("POST", f"{api}/proposals/{pid}/decision", "northstar", {"decision": "approve"}, expected=409)
    final = call("POST", f"{api}/proposals/{pid}/decision", "lakeview", {"decision": "approve", "comment": "Dock reviewed"})
    assert final["status"] == "approved_for_external_coordination" and final["version"] == 3
    assert final["snapshot"] == proposal["snapshot"]
    for org in ("northstar", "lakeview"):
        assert call("GET", api + "/proposals", org)[0] == final
        assert [e["event_type"] for e in call("GET", api + "/audit-events", org)] == [
            "demo.reset", "scan.completed", "proposal.created", "proposal.approved", "proposal.approved"]
    call("POST", api + "/demo/reset")
    rejected = call("POST", f"{api}/opportunities/{oid}/proposals", "lakeview", expected=201)
    assert rejected["id"] != pid
    closed = call("POST", f"{api}/proposals/{rejected['id']}/decision", "northstar", {"decision": "reject"})
    assert closed["status"] == "rejected"
    call("POST", f"{api}/proposals/{rejected['id']}/decision", "lakeview", {"decision": "approve"}, expected=409)
    call("POST", api + "/demo/reset")
    assert call("GET", api + "/proposals", "northstar") == []
    assert [e["event_type"] for e in call("GET", api + "/audit-events", "lakeview")] == ["demo.reset"]
    print(f"Verified HTTP demo flow; scan mode={result['mode']}, cached={result['cached']}. Seed restored.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--reset", action="store_true", help="Authorize clearing and exercising demo state")
    arguments = parser.parse_args()
    if not arguments.reset:
        parser.error("--reset is required: this script clears demo data and records user decisions")
    verify(arguments.base_url)
