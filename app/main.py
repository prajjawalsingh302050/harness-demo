"""Application factory: logging, middleware, routers and (locally) the static UI."""
from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.middleware import register_middleware


def create_app():
    configure_logging()
    app = FastAPI(title=settings.app_name, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    register_middleware(app)
    app.include_router(api_router)

    if settings.serve_static:
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="public")
    return app


app = create_app()
