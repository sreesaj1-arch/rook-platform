"""Application composition without import-time settings or global app state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rook_backend.api.health import router
from rook_backend.config import Settings
from rook_backend.database import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an independent API instance with validated configuration."""
    resolved_settings = settings if settings is not None else Settings()
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings)
        app.state.database = database
        try:
            yield
        finally:
            await database.close()
            del app.state.database

    app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.include_router(router)
    return app
