"""Order use cases: build the orders page with customer and order total."""
from app.core.config import settings
from app.schemas import OrderOut, OrdersPage


class OrderService:
    def __init__(self, orders, users):
        self.orders = orders
        self.users = users

    def list_orders(self, page):
        page = max(page, 1)
        size = settings.orders_page_size
        result = []
        for order in self.orders.list_page(size, (page - 1) * size):
            user = self.users.get(order["user_id"])
            total = self.orders.item_total(order["id"])
            result.append(OrderOut(
                id=order["id"],
                customer=user["name"],
                city=user["city"],
                created_at=order["created_at"],
                status=order["status"],
                total=total,
            ))
        return OrdersPage(page=page, page_size=size, orders=result)
