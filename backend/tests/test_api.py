import os
import tempfile
from datetime import timedelta

_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["DEMO"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.timeutil import iso, utcnow  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def mall(client):
    f1 = client.post("/api/floors", json={"name": "1 этаж", "sort": 1, "capacity": 100}).json()
    f2 = client.post("/api/floors", json={"name": "2 этаж", "sort": 2}).json()
    cam = client.post("/api/cameras", json={"name": "Вход", "floor_id": f1["id"]}).json()
    layout = client.put(
        f"/api/cameras/{cam['id']}/layout",
        json={
            "lines": [
                {"name": "Вход", "p1": [0, 0.5], "p2": [1, 0.5], "in_side": 1, "floor_in_id": f1["id"]},
                {"name": "Эскалатор", "p1": [0, 0.5], "p2": [1, 0.5], "floor_in_id": f2["id"], "floor_out_id": f1["id"]},
            ],
            "zones": [{"name": "Касса", "kind": "queue", "polygon": [[0, 0], [1, 0], [1, 1]], "floor_id": f1["id"]}],
        },
    ).json()
    return {"f1": f1, "f2": f2, "cam": cam, "entrance": layout["lines"][0], "escalator": layout["lines"][1],
            "zone": layout["zones"][0]}


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_occupancy_from_crossings(client, mall):
    now = iso(utcnow())
    r = client.post(
        "/api/ingest",
        json={
            "camera_id": mall["cam"]["id"],
            "crossings": [
                {"line_id": mall["entrance"]["id"], "direction": "in", "count": 10, "ts": now},
                {"line_id": mall["entrance"]["id"], "direction": "out", "count": 3, "ts": now},
                {"line_id": mall["escalator"]["id"], "direction": "in", "count": 4, "ts": now},
            ],
        },
    )
    assert r.status_code == 200

    ov = client.get("/api/overview").json()
    floors = {f["id"]: f["occupancy"] for f in ov["occupancy"]["floors"]}
    assert floors[mall["f1"]["id"]] == 7 - 4  # 10 вошли, 3 вышли, 4 поднялись
    assert floors[mall["f2"]["id"]] == 4
    assert ov["occupancy"]["mall"] == 7
    assert ov["visitors_today"] == 10


def test_manual_correction_resets_baseline(client, mall):
    client.post("/api/occupancy/correct", json={"floor_id": mall["f1"]["id"], "value": 50})
    ov = client.get("/api/overview").json()
    floors = {f["id"]: f["occupancy"] for f in ov["occupancy"]["floors"]}
    assert floors[mall["f1"]["id"]] == 50


def test_traffic_buckets(client, mall):
    end = utcnow() + timedelta(hours=1)
    start = end - timedelta(hours=6)
    rows = client.get("/api/traffic", params={"from": iso(start), "to": iso(end), "bucket": "hour"}).json()
    assert len(rows) >= 6
    assert sum(r["in"] for r in rows) == 10
    assert sum(r["out"] for r in rows) == 3
    assert all(r["occupancy"] is not None for r in rows)


def test_queue_and_heatmap(client, mall):
    client.post(
        "/api/ingest",
        json={
            "camera_id": mall["cam"]["id"],
            "queues": [{"zone_id": mall["zone"]["id"], "people": 6, "max_wait_sec": 200}],
            "tracks": [{"track_id": 1, "x": 0.5, "y": 0.5}, {"track_id": 2, "x": 0.51, "y": 0.5}],
        },
    )
    q = client.get("/api/queues").json()
    assert q[0]["people"] == 6 and q[0]["max_wait_sec"] == 200

    start, end = utcnow() - timedelta(hours=1), utcnow() + timedelta(minutes=1)
    hm = client.get(
        "/api/heatmap", params={"floor_id": mall["f1"]["id"], "from": iso(start), "to": iso(end)}
    ).json()
    assert hm["total"] == 2 and hm["max"] >= 1


def test_alert_fires_and_resolves(client, mall):
    from app.db import SessionLocal
    from app.services.alerts import AlertEngine

    rule = client.post(
        "/api/alert-rules",
        json={"name": "Очередь", "metric": "queue_people", "threshold": 5, "min_duration_sec": 0, "notify": False},
    ).json()
    engine = AlertEngine()
    with SessionLocal() as db:
        engine.tick(db)
    active = client.get("/api/overview").json()["alerts"]
    assert any(a["rule_id"] == rule["id"] for a in active)

    client.post(
        "/api/ingest",
        json={"camera_id": mall["cam"]["id"], "queues": [{"zone_id": mall["zone"]["id"], "people": 1}]},
    )
    with SessionLocal() as db:
        engine.tick(db)
    assert not any(a["rule_id"] == rule["id"] for a in client.get("/api/overview").json()["alerts"])


def test_layout_removes_missing_items(client, mall):
    cam = client.put(
        f"/api/cameras/{mall['cam']['id']}/layout",
        json={"lines": [mall["entrance"]], "zones": []},
    ).json()
    assert len(cam["lines"]) == 1 and cam["zones"] == []
