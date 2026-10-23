"""Response models. They are the API contract the UI in public/js depends on: keep them stable."""
from pydantic import BaseModel


class OrderOut(BaseModel):
    id: int
    customer: str
    city: str
    created_at: str
    status: str
    total: float


class OrdersPage(BaseModel):
    page: int
    page_size: int
    orders: list[OrderOut]


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    city: str
    order_count: int


class HealthOut(BaseModel):
    status: str
