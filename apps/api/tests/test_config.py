import pytest
from pydantic import ValidationError

from rook_backend.config import Settings


def test_default_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROOK_APP_NAME", raising=False)
    assert Settings().app_name == "Rook API"


def test_environment_and_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROOK_APP_NAME", "Environment API")
    assert Settings().app_name == "Environment API"
    assert Settings(app_name="Explicit API").app_name == "Explicit API"


@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_invalid_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv("ROOK_APP_NAME", name)
    with pytest.raises(ValidationError):
        Settings()
