from fastapi import APIRouter

from app.db import connect, query

router = APIRouter()


@router.get("/api/health")
def health():
    con = connect()
    try:
        query(con, "SELECT 1")
        return {"status": "ok"}
    finally:
        con.close()
