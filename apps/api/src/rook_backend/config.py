"""Validated configuration shared by backend entry points."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Only settings consumed by the current application."""

    model_config = SettingsConfigDict(
        env_prefix="ROOK_", frozen=True, hide_input_in_errors=True
    )

    app_name: str = Field(default="Rook API", min_length=1, pattern=r"\S")
    db_host: str = Field(default="postgres", min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(default="rook_local", min_length=1)
    db_user: str = Field(default="rook_local", min_length=1)
    db_password: SecretStr | None = Field(default=None, repr=False)
    readiness_timeout_seconds: float = Field(default=3.0, ge=0.05, le=10.0)
