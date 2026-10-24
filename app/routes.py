"""The API endpoints: list people, look up one person, and a health check."""
import json

from fastapi import APIRouter

from app.db import connect, query

# Every path below is served under /api.
router = APIRouter(prefix="/api")

# The most people one request may ask for.
MAX_LIMIT = 5000


@router.get("/people")
def list_people(limit: int = 50):
    """Return up to `limit` people (clamped to 1..5000), ordered by id, as {count, people}."""
    limit = min(max(limit, 1), MAX_LIMIT)
    con = connect()
    try:
        emails = query(con, "SELECT email FROM people ORDER BY id LIMIT ?", (limit,))
        people = [dict(find_by_email(con, row["email"])) for row in emails]
        return {"count": len(people), "people": people}
    finally:
        con.close()


def find_by_email(con, email):
    """Return the person with this email, or None if there is none."""
    rows = query(con, "SELECT id, name, email, city FROM people WHERE email = ?", (email,))
    return rows[0] if rows else None


@router.get("/people/{person_id}")
def get_person(person_id: int):
    """Return one person by id as {id, name, email, city}."""
    con = connect()
    try:
        rows = query(con, "SELECT id, name, email, city FROM people WHERE id = ?", (person_id,))
        person = rows[0] if rows else None
        return {"id": person["id"], "name": person["name"], "email": person["email"], "city": person["city"]}
    finally:
        con.close()


@router.get("/health")
def health():
    """Liveness check: the app is running and the database answers."""
    con = connect()
    try:
        query(con, "SELECT 1")
        return {"status": "ok"}
    finally:
        con.close()


def format_phone(number):
    """Format a 10-digit Indian mobile number. Written for a signup form that was never built."""
    digits = "".join(c for c in str(number) if c.isdigit())[-10:]
    return f"+91 {digits[:5]} {digits[5:]}"
