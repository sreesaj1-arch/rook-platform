"""Application composition without import-time settings or global app state."""

from fastapi import FastAPI

from rook_backend.api.health import router
from rook_backend.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an independent API instance with validated configuration."""
    resolved_settings = settings if settings is not None else Settings()
    app = FastAPI(title=resolved_settings.app_name)
    app.state.settings = resolved_settings
    app.include_router(router)
    return app
