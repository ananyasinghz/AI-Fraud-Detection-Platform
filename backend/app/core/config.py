"""Typed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
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
    database_url: str = "sqlite:///./data/processed/fraud.db"
    data_dir: Path = Path("data")
    model_dir: Path = Path("models")
    policy_config_path: Path = Path("config/policy/reporting_thresholds.v1.yaml")
    scenario_config_path: Path = Path("config/generation/scenario_catalog.v1.yaml")
    raw_creditcard_path: Path = Path("dataset/creditcard.csv")
    development_seed: int = Field(default=42, ge=0)
    heldout_seed: int = Field(default=99, ge=0)
    ml_enabled: bool = True
    ml_model_dir: Path = Path("models/ulb_v1/selected")
    node_timeout_seconds: float = Field(default=30.0, gt=0)
    node_max_retries: int = Field(default=1, ge=0, le=3)
    ollama_enabled: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout_seconds: float = Field(default=30.0, gt=0)
    intent_confidence_floor: float = Field(default=0.55, ge=0, le=1)
    intent_parser_version: str = Field(default="intent_parser.v1", min_length=1)
    planner_enabled: bool = False
    planner_version: str = Field(default="dynamic_planner.v1", min_length=1)
    planner_max_steps: int = Field(default=20, ge=1, le=20)
    graph_enabled: bool = True
    retrieval_enabled: bool = True
    chroma_persist_dir: Path = Path("data/runtime/chroma_policy")
    policy_corpus_path: Path = Path("config/policy/corpus/policy_excerpts.v1.json")
    retrieval_top_k: int = Field(default=3, ge=1, le=20)

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Require one normalized, non-root API prefix."""
        normalized = value.rstrip("/")
        if not normalized.startswith("/") or normalized == "":
            raise ValueError("api_prefix must start with '/' and cannot be root")
        return normalized

    @model_validator(mode="after")
    def validate_distinct_seeds(self) -> "Settings":
        """Keep development and held-out scenario populations separate."""
        if self.development_seed == self.heldout_seed:
            raise ValueError("development_seed and heldout_seed must differ")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide immutable-by-convention settings instance."""
    return Settings()
