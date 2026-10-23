"""Liveness: the app is up and the database answers."""
from app.db import query
from app.schemas import HealthOut


class HealthService:
    def __init__(self, con):
        self.con = con

    def check(self):
        query(self.con, "SELECT 1")
        return HealthOut(status="ok")
