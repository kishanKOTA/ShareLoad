"""Shipment extraction tests. Gemini is mocked; no network calls."""

import json
import shutil
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app.ingestion import extract as extract_mod
from app.main import create_app
from app.matching.scan import DEMO_DIR, clear_scan_cache
from app.schemas import Shipment

URL = "/api/v1/ingest/shipments/parse"
LAKEVIEW = {"X-Org-Id": "lakeview"}

SHIP_B = next(
    s for s in json.loads((DEMO_DIR / "shipments.json").read_text(encoding="utf-8"))
    if s["id"] == "ship-b"
)
CONTRACT_FIELDS = (
    "origin", "destination", "weight_kg", "volume_m3", "cargo_type", "hazardous",
    "temp_min_c", "temp_max_c", "pickup_window", "delivery_window",
)


def gemini_reply(**overrides):
    """What Gemini should return for the ship-b email."""
    body = {k: SHIP_B[k] for k in CONTRACT_FIELDS}
    body |= {"confidence": 0.94, "missing_fields": []}
    body |= overrides
    return json.dumps(body)


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)


@pytest.fixture
def data_dir(tmp_path):
    shutil.copytree(DEMO_DIR, tmp_path / "demo")
    yield tmp_path / "demo"
    clear_scan_cache()


@pytest.fixture
def gemini(monkeypatch, data_dir):
    """Returns (TestClient, set_replies); set_replies(...) -> the FakeModels."""
    monkeypatch.setattr(extract_mod, "get_config", lambda: SimpleNamespace(gemini_model="test-model"))
    holder = {}

    def set_replies(*replies):
        holder["models"] = FakeModels(replies)
        return holder["models"]

    monkeypatch.setattr(main_mod, "get_gemini_client", lambda: SimpleNamespace(models=holder["models"]))
    return TestClient(create_app(data_dir=data_dir, use_gemini=True)), set_replies


def post(client, text=SHIP_B["raw_text"], headers=LAKEVIEW):
    return client.post(URL, json={"raw_text": text}, headers=headers)


def test_ship_b_email_extracts_schema_valid_shipment(gemini):
    client, set_replies = gemini
    models = set_replies(gemini_reply())

    r = post(client)

    assert r.status_code == 200, r.text
    shipment = Shipment.model_validate(r.json())
    expected = Shipment.model_validate(SHIP_B)
    for field in CONTRACT_FIELDS:
        assert getattr(shipment, field) == getattr(expected, field), field
    assert shipment.org_id == "lakeview"
    assert shipment.raw_text == SHIP_B["raw_text"]
    assert shipment.id.startswith("ship-") and shipment.id != "ship-b"
    assert shipment.extraction.confidence == 0.94
    assert shipment.extraction.missing_fields == []
    assert shipment.missing_critical_fields() == []

    assert len(models.calls) == 1
    call = models.calls[0]
    assert call["model"] == "test-model"
    assert SHIP_B["raw_text"] in call["contents"]
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is extract_mod._ExtractedShipment


def test_bad_json_is_retried_once(gemini):
    client, set_replies = gemini
    models = set_replies("{not json", gemini_reply())

    r = post(client)

    assert r.status_code == 200, r.text
    assert len(models.calls) == 2
    assert r.json()["weight_kg"] == 1200


def test_schema_invalid_output_is_retried(gemini):
    client, set_replies = gemini
    naive = {"start": "2026-11-20T08:00:00", "end": "2026-11-20T12:00:00"}
    models = set_replies(gemini_reply(pickup_window=naive), gemini_reply())

    r = post(client)

    assert r.status_code == 200, r.text
    assert len(models.calls) == 2


def test_bad_json_twice_returns_502(gemini):
    client, set_replies = gemini
    models = set_replies("{not json", "")

    r = post(client)

    assert r.status_code == 502
    assert "invalid shipment JSON" in r.json()["detail"]
    assert len(models.calls) == 2


def test_gemini_error_is_not_retried(gemini):
    client, set_replies = gemini
    models = set_replies(RuntimeError("quota exceeded"))

    r = post(client)

    assert r.status_code == 502
    assert "quota exceeded" in r.json()["detail"]
    assert len(models.calls) == 1


def test_missing_fields_are_flagged(gemini):
    client, set_replies = gemini
    # Gemini leaves weight null and forgets to flag it; flags the window itself.
    set_replies(gemini_reply(weight_kg=None, delivery_window=None,
                             confidence=0.6, missing_fields=["delivery_window"]))

    r = post(client)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weight_kg"] is None
    assert body["extraction"] == {"confidence": 0.6, "missing_fields": ["weight_kg", "delivery_window"]}


def test_no_api_key_returns_503(data_dir, monkeypatch):
    monkeypatch.setattr(main_mod, "get_gemini_client", lambda: None)
    client = TestClient(create_app(data_dir=data_dir, use_gemini=True))

    r = post(client)

    assert r.status_code == 503
    assert "GEMINI_API_KEY" in r.json()["detail"]


def test_gemini_disabled_returns_503(data_dir):
    client = TestClient(create_app(data_dir=data_dir, use_gemini=False))
    assert post(client).status_code == 503


@pytest.mark.parametrize("headers, status", [({}, 422), ({"X-Org-Id": "nobody"}, 403)])
def test_requires_known_org(gemini, headers, status):
    client, set_replies = gemini
    set_replies(gemini_reply())
    assert post(client, headers=headers).status_code == status


def test_empty_text_rejected(gemini):
    client, _ = gemini
    assert post(client, text="").status_code == 422
