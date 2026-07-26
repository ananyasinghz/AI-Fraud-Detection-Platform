"""Versioned synthetic-data configuration loading."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from backend.app.domain.base import ContractModel
from backend.app.generation.contracts import AwareDatetime, ScenarioType
from backend.app.policy.config import PolicyConfig, StructuringPolicy, load_policy_config


class GenerationConfig(ContractModel):
    version: str
    generator_version: str
    as_of: AwareDatetime
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    baseline_customer_count: int = Field(ge=1)
    baseline_transactions_per_customer: int = Field(ge=1)
    scenarios_per_pattern: int = Field(ge=1)
    patterns: list[ScenarioType]


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one YAML mapping")
    return value


def load_generation_config(path: Path) -> GenerationConfig:
    return GenerationConfig.model_validate(_read_yaml(path))


__all__ = [
    "GenerationConfig",
    "PolicyConfig",
    "StructuringPolicy",
    "load_generation_config",
    "load_policy_config",
]
