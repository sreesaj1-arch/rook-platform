"""Validated configuration shared by backend entry points."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Only settings consumed by the current application."""

    model_config = SettingsConfigDict(env_prefix="ROOK_", frozen=True)

    app_name: str = Field(default="Rook API", min_length=1, pattern=r"\S")
