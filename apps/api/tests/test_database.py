import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from rook_backend.api.app import create_app
from rook_backend.config import Settings


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout", "wrong-result"])
def test_database_probe_and_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    outcome: str,
) -> None:
    engine = MagicMock()
    connection = MagicMock()
    connection.scalar = AsyncMock(return_value=1 if outcome == "success" else 0)
    engine.connect.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    if outcome == "failure":
        engine.connect.return_value.__aenter__.side_effect = OperationalError(
            "SELECT 1", {}, Exception("private-credential-and-host")
        )
    if outcome == "timeout":
        async def stalled_query(*args: object) -> int:
            await asyncio.sleep(30)
            return 1

        connection.scalar.side_effect = stalled_query
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr("rook_backend.database.create_async_engine", factory)
    app = create_app(Settings(
        db_password=SecretStr("private-credential-and-host"),
        readiness_timeout_seconds=0.05,
    ))
    factory.assert_not_called()
    with TestClient(app) as client:
        factory.assert_called_once()
        started = time.monotonic()
        response = client.get("/health/ready")
        if outcome == "timeout":
            assert time.monotonic() - started < 1.0
        expected = outcome == "success"
        assert response.status_code == (200 if expected else 503)
        assert response.json() == {"status": "ready" if expected else "unavailable"}
        assert "private-credential-and-host" not in response.text + caplog.text
        before = engine.connect.call_count
        live = client.get("/health/live")
        assert live.status_code == 200
        assert live.json() == {"status": "alive"}
        assert engine.connect.call_count == before
        engine.dispose.assert_not_awaited()
    engine.dispose.assert_awaited_once()
    assert not hasattr(app.state, "database")
    if outcome != "failure":
        assert str(connection.scalar.call_args.args[0]) == "SELECT 1"
        engine.connect.return_value.__aexit__.assert_awaited_once()


def test_unconfigured_database_is_unavailable() -> None:
    with TestClient(create_app(Settings(db_password=None))) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/ready").json() == {"status": "unavailable"}
        assert client.get("/health/live").status_code == 200


def test_probe_recovers_without_recreating_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = MagicMock()
    connection = MagicMock()
    connection.scalar = AsyncMock(side_effect=[
        1, OperationalError("SELECT 1", {}, Exception("unavailable")), 1,
    ])
    engine.connect.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("rook_backend.database.create_async_engine", lambda *a, **k: engine)
    with TestClient(create_app(Settings(db_password=SecretStr("test-only")))) as client:
        assert [client.get("/health/ready").status_code for _ in range(3)] == [200, 503, 200]
