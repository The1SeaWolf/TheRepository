import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config, foods, vision


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "APP_PASSWORD", "")
    from app.main import app
    with TestClient(app) as c:
        yield c


ENTRY = {"day": "2026-10-25", "meal": "lunch", "name": "Rice", "amount": "1 cup", "carbs_g": 45.04, "fat_g": 0.4}


def test_diary_totals_and_goals(client):
    client.post("/api/entries", json=ENTRY)
    client.post("/api/entries", json={**ENTRY, "name": "Butter", "carbs_g": 0, "fat_g": 11.5})
    client.put("/api/goals", json={"carbs_g": 100, "fat_g": None})
    d = client.get("/api/day/2026-10-25").json()
    assert d["totals"] == {"carbs_g": 45.0, "fat_g": 11.9}
    assert d["goals"] == {"carbs_g": 100.0, "fat_g": None}
    assert [r["name"] for r in client.get("/api/recent").json()] == ["Butter", "Rice"]


def test_delete_and_validation(client):
    eid = client.post("/api/entries", json=ENTRY).json()["id"]
    assert client.delete(f"/api/entries/{eid}").status_code == 200
    assert client.delete(f"/api/entries/{eid}").status_code == 404
    assert client.post("/api/entries", json={**ENTRY, "carbs_g": -1}).status_code == 422
    assert client.post("/api/entries", json={**ENTRY, "day": "tomorrow"}).status_code == 422


def test_history_fills_empty_days(client):
    client.post("/api/entries", json=ENTRY)
    h = client.get("/api/history?days=3&end=2026-10-26").json()["days"]
    assert [d["carbs_g"] for d in h] == [0, 45.0, 0]


def test_basic_auth(client, monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD", "pw")
    assert client.get("/api/goals").status_code == 401
    assert client.get("/healthz").status_code == 200
    good = "Basic " + base64.b64encode(b"carbs:pw").decode()
    assert client.get("/api/goals", headers={"Authorization": good}).status_code == 200
    bad = "Basic " + base64.b64encode(b"carbs:no").decode()
    assert client.get("/api/goals", headers={"Authorization": bad}).status_code == 401
    assert client.get("/api/goals", headers={"Authorization": "Basic !!!"}).status_code == 401


def test_parse_off_product():
    f = foods.parse_off_product({"code": "1", "product_name": "Oats", "brands": "Acme, Foo", "serving_quantity": 40,
                                 "serving_size": "40 g", "nutriments": {"carbohydrates_100g": 60, "fat_100g": 7}})
    assert f["brand"] == "Acme" and f["carbs_serving"] == 24 and f["fat_serving"] == 2.8
    assert foods.parse_off_product({"product_name": "No data", "nutriments": {}}) is None


def test_parse_usda_food():
    f = foods.parse_usda_food({"description": "BANANAS, RAW", "foodNutrients": [
        {"nutrientId": 1005, "value": 22.8}, {"nutrientId": 1004, "value": 0.33}]})
    assert f["name"] == "Bananas, Raw" and f["carbs_100g"] == 22.8 and "carbs_serving" not in f


def test_barcode_rejects_bad_input(client):
    assert client.get("/api/barcode/abc").status_code == 400


def test_label_analysis_uses_claude(client, monkeypatch):
    payload = {"is_label": True, "name": "Cereal", "serving_desc": "1 cup", "serving_g": 30,
               "servings_per_container": 10, "carbs_g": 24, "fat_g": 1.5, "notes": ""}
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(vision.anthropic, "Anthropic",
                        lambda **kw: SimpleNamespace(messages=SimpleNamespace(create=create)))
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 20
    r = client.post("/api/analyze/label", files={"image": ("a.jpg", jpeg, "image/jpeg")})
    assert r.status_code == 200 and r.json()["carbs_g"] == 24
    assert seen["model"] == config.CLAUDE_MODEL
    assert seen["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_analysis_errors(client, monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 20
    r = client.post("/api/analyze/meal", files={"image": ("a.jpg", jpeg, "image/jpeg")})
    assert r.status_code == 422 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    r = client.post("/api/analyze/meal", files={"image": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 422
