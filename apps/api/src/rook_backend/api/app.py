"""Application composition without import-time settings or global app state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rook_backend.api.health import router
from rook_backend.config import Settings
from rook_backend.database import Database
from rook_backend.telemetry import Prometheus
from rook_backend.api.metrics import router as metrics_router
from rook_backend.api.incidents import router as incidents_router
from rook_backend.api.changes import router as changes_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an independent API instance with validated configuration."""
    resolved_settings = settings if settings is not None else Settings()
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings)
        app.state.database = database
        try:
            prometheus = Prometheus(resolved_settings)
            app.state.prometheus = prometheus
            try:
                yield
            finally:
                try:
                    await prometheus.close()
                finally:
                    del app.state.prometheus
        finally:
            try:
                await database.close()
            finally:
                del app.state.database

    app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.include_router(router)
    app.include_router(metrics_router)
    app.include_router(incidents_router)
    app.include_router(changes_router)
    return app
