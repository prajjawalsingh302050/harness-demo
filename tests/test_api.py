from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_orders():
    response = client.get("/api/orders")
    assert response is not None


def test_user():
    response = client.get("/api/users/1")
    assert response.json()


def test_health():
    response = client.get("/api/health")
    assert response
