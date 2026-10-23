"""Service registry: the one place that wires repositories into services.

A registry is created per request around one database connection. Routes never build
services or repositories themselves; they ask the registry (see app/api/deps.py).
Services are created lazily and cached, so a request only builds what it uses.
"""
from functools import cached_property

from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository
from app.services.health import HealthService
from app.services.orders import OrderService
from app.services.users import UserService


class ServiceRegistry:
    def __init__(self, con):
        self.con = con

    # repositories
    @cached_property
    def order_repo(self):
        return OrderRepository(self.con)

    @cached_property
    def user_repo(self):
        return UserRepository(self.con)

    # services
    @cached_property
    def orders(self):
        return OrderService(self.order_repo, self.user_repo)

    @cached_property
    def users(self):
        return UserService(self.user_repo, self.order_repo)

    @cached_property
    def health(self):
        return HealthService(self.con)
