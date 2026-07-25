"""Typed application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FRAUD_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="Suspicious Activity Detection API", min_length=1)
    app_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_prefix: str = "/api/v1"
    contract_version: Literal["v1"] = "v1"

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Require one normalized, non-root API prefix."""
        normalized = value.rstrip("/")
        if not normalized.startswith("/") or normalized == "":
            raise ValueError("api_prefix must start with '/' and cannot be root")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide immutable-by-convention settings instance."""
    return Settings()
