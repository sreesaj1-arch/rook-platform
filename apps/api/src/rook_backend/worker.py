"""Sequential incident evaluation process; API startup never starts this worker."""

import asyncio
import signal
import sys
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from rook_backend.config import Settings
from rook_backend.database import Database
from rook_backend.incident_store import PostgresIncidentStore
from rook_backend.incidents import Rules, evaluate_service
from rook_backend.telemetry import Prometheus, SERVICE, Unavailable

HEARTBEAT = Path('/tmp/rook-worker-heartbeat')


class WorkerSettings(Settings):
    """Worker-only settings do not affect API configuration validation."""

    worker_services: tuple[Annotated[str, Field(pattern=f'^{SERVICE}$')], ...] = Field(
        default=('frontend',), min_length=1, max_length=20)
    worker_interval_seconds: float = Field(default=30, ge=1, le=3600, allow_inf_nan=False)
    worker_error_ratio: float | None = Field(default=0.05, ge=0, le=1, allow_inf_nan=False)
    worker_p95_seconds: float | None = Field(default=0.5, gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def validate_worker(self) -> Self:
        if len(set(self.worker_services)) != len(self.worker_services):
            raise ValueError('Worker service names must be unique')
        if self.worker_error_ratio is None and self.worker_p95_seconds is None:
            raise ValueError('At least one worker threshold is required')
        return self


@asynccontextmanager
async def ownership(database: Database) -> AsyncIterator[bool]:
    """Nonblocking PostgreSQL ownership per sweep; released on cancel/rollback."""
    if database.engine is None:
        raise Unavailable()
    try:
        async with database.engine.begin() as connection:
            acquired = await connection.scalar(text('SELECT pg_try_advisory_xact_lock(73190503)'))
            yield bool(acquired)
    except (SQLAlchemyError, OSError):
        raise Unavailable() from None


async def wait_interval(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def run_worker(settings: WorkerSettings, stop: asyncio.Event,
                     heartbeat: Path | None = None) -> None:
    """Own clients, evaluate immediately then wait after each completed sweep."""
    database = Database(settings)
    try:
        source = Prometheus(settings)
        try:
            store = PostgresIncidentStore(database)
            rules = Rules(error_ratio=settings.worker_error_ratio, p95_latency=settings.worker_p95_seconds)
            print('worker started', flush=True)
            while not stop.is_set():
                try:
                    # Includes ownership acquisition, initialization and all services.
                    budget = 15 + len(settings.worker_services) * (settings.prometheus_deadline_seconds + 12)
                    async with asyncio.timeout(budget):
                        async with ownership(database) as acquired:
                            if acquired:
                                # Idempotent initial schema only, no destructive migrations.
                                await store.initialize()
                                for service in settings.worker_services:
                                    if stop.is_set():
                                        break
                                    try:
                                        async with asyncio.timeout(settings.prometheus_deadline_seconds + 12):
                                            result = await evaluate_service(service, source, store, rules)
                                        print(f'worker service={service} status={result.status} incident_count={len(result.incidents)}', flush=True)
                                    except (Unavailable, TimeoutError):
                                        print(f'worker service={service} status=unavailable', flush=True)
                            else:
                                print('worker sweep skipped: ownership busy', flush=True)
                except (Unavailable, TimeoutError):
                    print('worker sweep unavailable', flush=True)
                if heartbeat is not None:
                    heartbeat.write_text(str(time.monotonic()), encoding='ascii')
                await wait_interval(stop, settings.worker_interval_seconds)
        finally:
            await source.close()
    finally:
        try:
            await database.close()
        finally:
            if heartbeat is not None:
                heartbeat.unlink(missing_ok=True)
            print('worker stopped', flush=True)


async def serve(settings: WorkerSettings) -> None:
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: loop.call_soon_threadsafe(task.cancel))
    try:
        await run_worker(settings, asyncio.Event(), HEARTBEAT if sys.platform != 'win32' else None)
    finally:
        signal.signal(signal.SIGTERM, previous)


def main() -> int:
    try:
        settings = WorkerSettings()
        if '--healthcheck' in sys.argv:
            # Reports loop progress, not Prometheus/database/workload health.
            budget = 15 + len(settings.worker_services) * (settings.prometheus_deadline_seconds + 12)
            age = time.monotonic() - float(HEARTBEAT.read_text(encoding='ascii'))
            return 0 if 0 <= age <= settings.worker_interval_seconds + budget + 15 else 1
        asyncio.run(serve(settings), loop_factory=asyncio.SelectorEventLoop if sys.platform == 'win32' else None)
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 0
    except Exception:
        # Settings, database and HTTP exception details may contain credentials.
        print('worker failed; check configuration and dependency availability', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
