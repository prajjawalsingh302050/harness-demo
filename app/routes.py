from fastapi import APIRouter, HTTPException

from app.db import connect, query

router = APIRouter(prefix="/api")

MAX_LIMIT = 5000


@router.get("/people")
def list_people(limit: int = 50):
    limit = min(max(limit, 1), MAX_LIMIT)
    con = connect()
    try:
        rows = query(con, "SELECT id, name, email, city FROM people ORDER BY id LIMIT ?", (limit,))
        people = [dict(row) for row in rows]
        return {"count": len(people), "people": people}
    finally:
        con.close()


@router.get("/people/{person_id}")
def get_person(person_id: int):
    con = connect()
    try:
        rows = query(con, "SELECT id, name, email, city FROM people WHERE id = ?", (person_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Person not found")
        person = rows[0]
        return {"id": person["id"], "name": person["name"], "email": person["email"], "city": person["city"]}
    finally:
        con.close()


@router.get("/health")
def health():
    con = connect()
    try:
        query(con, "SELECT 1")
        return {"status": "ok"}
    finally:
        con.close()
