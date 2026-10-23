"""Data access for orders and order items. SQL lives here and nowhere else."""
from app.db import query


class OrderRepository:
    def __init__(self, con):
        self.con = con

    def list_page(self, limit, offset):
        return query(
            self.con,
            "SELECT id, user_id, created_at, status FROM orders ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    def item_total(self, order_id):
        row = query(
            self.con,
            "SELECT SUM(qty * unit_price) AS total FROM order_items WHERE order_id = ?",
            (order_id,),
        )[0]
        return row["total"] or 0

    def count_for_user(self, user_id):
        return query(self.con, "SELECT COUNT(*) AS n FROM orders WHERE user_id = ?", (user_id,))[0]["n"]
