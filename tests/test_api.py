from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_orders():
    response = client.get("/api/orders")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert len(body["orders"]) == 50
    first = body["orders"][0]
    assert set(first) == {"id", "customer", "city", "created_at", "status", "total"}
    assert first["total"] > 0


def test_orders_paging():
    first = client.get("/api/orders?page=1").json()["orders"]
    second = client.get("/api/orders?page=2").json()["orders"]
    assert {o["id"] for o in first}.isdisjoint(o["id"] for o in second)


def test_user():
    response = client.get("/api/users/1")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "Ishaan Sharma"
    assert body["city"] == "Lucknow"
    assert body["order_count"] == 14


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
