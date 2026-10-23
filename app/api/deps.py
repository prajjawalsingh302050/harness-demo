"""FastAPI dependencies: one connection and one service registry per request."""
from fastapi import Depends

from app.db import connect
from app.services.registry import ServiceRegistry


def get_db():
    con = connect()
    try:
        yield con
    finally:
        con.close()


def get_services(con=Depends(get_db)):
    return ServiceRegistry(con)
