from fastapi.testclient import TestClient

from api.index import app

client = TestClient(app)


def test_people_default():
    response = client.get("/api/people")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 50
    assert len(body["people"]) == 50
    assert body["people"][0] == {"id": 1, "name": "Ishaan Sharma", "email": "ishaan.sharma1@example.com", "city": "Lucknow"}


def test_people_5000():
    body = client.get("/api/people?limit=5000").json()
    assert body["count"] == 5000
    assert [p["id"] for p in body["people"]] == list(range(1, 5001))


def test_person():
    response = client.get("/api/people/10000")
    assert response.status_code == 200
    assert response.json() == {"id": 10000, "name": "Vikram Das", "email": "vikram.das10000@example.com", "city": "Mumbai"}


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
