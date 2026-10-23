"""Customer use cases: one customer with their order count."""
from app.schemas import UserOut


class UserService:
    def __init__(self, users, orders):
        self.users = users
        self.orders = orders

    def get_user(self, user_id):
        user = self.users.get(user_id)
        return UserOut(
            id=user["id"],
            name=user["name"],
            email=user["email"],
            city=user["city"],
            order_count=self.orders.count_for_user(user_id),
        )
