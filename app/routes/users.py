from fastapi import APIRouter

from app.db import connect, query

router = APIRouter()


@router.get("/api/users/{user_id}")
def get_user(user_id: int):
    con = connect()
    try:
        rows = query(con, "SELECT id, name, email, city FROM users WHERE id = ?", (user_id,))
        user = rows[0] if rows else None
        order_count = query(con, "SELECT COUNT(*) AS n FROM orders WHERE user_id = ?", (user_id,))[0]["n"]
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "city": user["city"],
            "order_count": order_count,
        }
    finally:
        con.close()
