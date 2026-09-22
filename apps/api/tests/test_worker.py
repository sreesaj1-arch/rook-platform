import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from rook_backend.config import Settings
from rook_backend.worker import WorkerSettings, run_worker, wait_interval, ownership
from rook_backend.telemetry import Unavailable
from .test_incidents import SQLiteStore, snapshot


@pytest.mark.parametrize('patch', [
    {'worker_interval_seconds': 0}, {'worker_interval_seconds': float('nan')},
    {'worker_services': []}, {'worker_services': ['unsafe{']},
    {'worker_services': ['frontend', 'frontend']},
    {'worker_error_ratio': None, 'worker_p95_seconds': None},
])
def test_config_validation(patch):
    with pytest.raises(ValidationError):
        WorkerSettings(**patch)


def test_worker_environment_is_independent_of_api(monkeypatch):
    monkeypatch.setenv('ROOK_WORKER_INTERVAL_SECONDS', '42')
    monkeypatch.setenv('ROOK_WORKER_SERVICES', '["frontend","checkout"]')
    assert WorkerSettings().worker_interval_seconds == 42
    assert WorkerSettings().worker_services == ('frontend', 'checkout')
    assert not hasattr(Settings(), 'worker_services')
    monkeypatch.setenv('ROOK_WORKER_INTERVAL_SECONDS', 'bad')
    assert Settings().app_name == 'Rook API'
    with pytest.raises(ValidationError):
        WorkerSettings()


def test_wait_interval_uses_configured_seconds_and_interrupts(monkeypatch):
    async def check():
        async def wait(awaitable, timeout):
            assert timeout == 42
            await awaitable
        monkeypatch.setattr('rook_backend.worker.asyncio.wait_for', wait)
        stop = asyncio.Event()
        stop.set()
        await wait_interval(stop, 42)
    asyncio.run(check())


@pytest.mark.parametrize('quality', ['measured', 'stale', 'insufficient_data', 'unavailable'])
def test_repeated_sweeps_reuse_evaluator_and_deduplicate(monkeypatch, quality):
    async def check():
        stop = asyncio.Event()
        database, source = MagicMock(), AsyncMock()
        database.close = AsyncMock()
        source.metrics.return_value = snapshot(value=None if quality == 'insufficient_data' else 0.2,
                                               status=quality if quality != 'unavailable' else 'measured')
        if quality == 'unavailable':
            source.metrics.side_effect = Unavailable()
        store = SQLiteStore()
        @asynccontextmanager
        async def lock(db):
            yield True
        waits = []
        async def wait(event, seconds):
            waits.append(seconds)
            if len(waits) == 3:
                event.set()
        monkeypatch.setattr('rook_backend.worker.Database', lambda s: database)
        monkeypatch.setattr('rook_backend.worker.Prometheus', lambda s: source)
        monkeypatch.setattr('rook_backend.worker.PostgresIncidentStore', lambda db: store)
        monkeypatch.setattr('rook_backend.worker.ownership', lock)
        monkeypatch.setattr('rook_backend.worker.wait_interval', wait)
        try:
            await run_worker(WorkerSettings(worker_interval_seconds=42, worker_p95_seconds=None), stop)
            assert waits == [42, 42, 42]
            assert source.metrics.await_count == 3
            assert len(await store.list()) == (1 if quality == 'measured' else 0)
            source.close.assert_awaited_once()
            database.close.assert_awaited_once()
        finally:
            store.engine.dispose()
    asyncio.run(check())


def test_cancellation_releases_ownership_and_clients(monkeypatch):
    async def check():
        entered, released = asyncio.Event(), asyncio.Event()
        database, source, store = MagicMock(), AsyncMock(), AsyncMock()
        database.close = AsyncMock()
        async def stalled(service):
            entered.set()
            await asyncio.Event().wait()
        source.metrics.side_effect = stalled
        @asynccontextmanager
        async def lock(db):
            try:
                yield True
            finally:
                released.set()
        monkeypatch.setattr('rook_backend.worker.Database', lambda s: database)
        monkeypatch.setattr('rook_backend.worker.Prometheus', lambda s: source)
        monkeypatch.setattr('rook_backend.worker.PostgresIncidentStore', lambda db: store)
        monkeypatch.setattr('rook_backend.worker.ownership', lock)
        heartbeat = MagicMock()
        task = asyncio.create_task(run_worker(WorkerSettings(), asyncio.Event(), heartbeat))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert released.is_set()
        heartbeat.unlink.assert_called_once_with(missing_ok=True)
        source.close.assert_awaited_once()
        database.close.assert_awaited_once()
    asyncio.run(check())


def test_initialization_failure_closes_database(monkeypatch):
    database = MagicMock()
    database.close = AsyncMock()
    monkeypatch.setattr('rook_backend.worker.Database', lambda s: database)
    def fail(settings):
        raise RuntimeError('test-only initialization failure')
    monkeypatch.setattr('rook_backend.worker.Prometheus', fail)
    with pytest.raises(RuntimeError):
        asyncio.run(run_worker(WorkerSettings(), asyncio.Event()))
    database.close.assert_awaited_once()


def test_ownership_uses_nonblocking_transaction_lock():
    async def check():
        database = MagicMock()
        connection = MagicMock()
        connection.scalar = AsyncMock(return_value=False)
        transaction = database.engine.begin.return_value
        transaction.__aenter__ = AsyncMock(return_value=connection)
        transaction.__aexit__ = AsyncMock(return_value=False)
        async with ownership(database) as acquired:
            assert not acquired
        assert 'pg_try_advisory_xact_lock' in str(connection.scalar.call_args.args[0])
        transaction.__aexit__.assert_awaited_once()
    asyncio.run(check())
