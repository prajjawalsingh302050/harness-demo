"""API tests. They call the app in-process and check status codes and exact values."""
from fastapi.testclient import TestClient

from api.index import app

# A client that calls the app directly, without starting a server.
client = TestClient(app)


def test_people_default():
    """The default list has 50 people, starting with person 1."""
    response = client.get("/api/people")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 50
    assert len(body["people"]) == 50
    assert body["people"][0] == {"id": 1, "name": "Ishaan Sharma", "email": "ishaan.sharma1@example.com", "city": "Lucknow"}


def test_people_5000():
    """limit=5000 returns exactly ids 1..5000, in order."""
    body = client.get("/api/people?limit=5000").json()
    assert body["count"] == 5000
    assert [p["id"] for p in body["people"]] == list(range(1, 5001))


def test_person():
    """Looking up the last person returns their exact record."""
    response = client.get("/api/people/10000")
    assert response.status_code == 200
    assert response.json() == {"id": 10000, "name": "Vikram Das", "email": "vikram.das10000@example.com", "city": "Mumbai"}


def test_person_not_found():
    """Looking up a missing person returns 404."""
    response = client.get("/api/people/15000")
    assert response.status_code == 404
    assert response.json() == {"detail": "Person not found"}


def test_health():
    """The health check answers {"status": "ok"}."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
