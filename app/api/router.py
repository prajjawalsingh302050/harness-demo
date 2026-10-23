"""Router registry: every route module is registered here, under /api.

To add an endpoint group, create app/api/routes/<name>.py with a `router` and add it to ROUTERS.
"""
from fastapi import APIRouter

from app.api.routes import health, orders, users

ROUTERS = [orders.router, users.router, health.router]

api_router = APIRouter(prefix="/api")
for router in ROUTERS:
    api_router.include_router(router)
