from fastapi.testclient import TestClient

from rook_backend.api.app import create_app
from rook_backend.config import Settings


def test_liveness_contract() -> None:
    with TestClient(create_app(Settings(app_name="Test API"))) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    # The exact body prevents adding unsupported dependency-health claims.
    assert response.json() == {"status": "alive"}
