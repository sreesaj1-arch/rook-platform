import pytest
from fastapi.testclient import TestClient

from rook_backend.api.app import create_app


def test_factory_isolates_configuration_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROOK_APP_NAME", "First API")
    first = create_app()
    monkeypatch.setenv("ROOK_APP_NAME", "Second API")
    second = create_app()
    first.state.marker = "first only"

    with TestClient(first) as first_client, TestClient(second) as second_client:
        assert first_client.get("/openapi.json").json()["info"]["title"] == "First API"
        assert second_client.get("/openapi.json").json()["info"]["title"] == "Second API"

    assert first.state.settings.app_name == "First API"
    assert second.state.settings.app_name == "Second API"
    assert not hasattr(second.state, "marker")
