import json

from fastapi import APIRouter, Depends

from app.api.deps import get_services
from app.schemas import OrdersPage

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=OrdersPage)
def list_orders(page: int = 1, services=Depends(get_services)):
    return services.orders.list_orders(page)
