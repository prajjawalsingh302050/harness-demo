import json

from fastapi import APIRouter

from app.db import connect, query
from app.services.pricing import price_with_tax

router = APIRouter()

PAGE_SIZE = 50


@router.get("/api/orders")
def list_orders(page: int = 1):
    page = max(page, 1)
    con = connect()
    try:
        orders = query(
            con,
            "SELECT id, user_id, created_at, status FROM orders ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE, (page - 1) * PAGE_SIZE),
        )
        result = []
        for order in orders:
            user = query(con, "SELECT name, city FROM users WHERE id = ?", (order["user_id"],))[0]
            total = query(
                con,
                "SELECT SUM(qty * unit_price) AS total FROM order_items WHERE order_id = ?",
                (order["id"],),
            )[0]["total"] or 0
            result.append({
                "id": order["id"],
                "customer": user["name"],
                "city": user["city"],
                "created_at": order["created_at"],
                "status": order["status"],
                "total": price_with_tax(total, user["city"]),
            })
        return {"page": page, "page_size": PAGE_SIZE, "orders": result}
    finally:
        con.close()
