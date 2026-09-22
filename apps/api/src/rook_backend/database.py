"""Lifespan-owned database resource and a bounded readiness query."""

import asyncio

from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from rook_backend.config import Settings


class Database:
    """Shared engine; each readiness probe opens and closes one connection."""

    def __init__(self, settings: Settings) -> None:
        self.timeout = settings.readiness_timeout_seconds
        self.engine: AsyncEngine | None = None
        if settings.db_password is not None:
            url = URL.create(
                "postgresql+psycopg",
                username=settings.db_user,
                password=settings.db_password.get_secret_value(),
                host=settings.db_host,
                port=settings.db_port,
                database=settings.db_name,
            )
            self.engine = create_async_engine(
                url,
                poolclass=NullPool,
                echo=False,
                hide_parameters=True,
                connect_args={
                    "connect_timeout": 2,
                    "options": "-c statement_timeout=2000",
                },
            )

    async def ready(self) -> bool:
        if self.engine is None:
            return False
        try:
            async with asyncio.timeout(self.timeout):
                async with self.engine.connect() as connection:
                    return (await connection.scalar(text("SELECT 1"))) == 1
        except (SQLAlchemyError, OSError, TimeoutError):
            # Never expose or log exception text, connection URLs, or credentials.
            return False

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
