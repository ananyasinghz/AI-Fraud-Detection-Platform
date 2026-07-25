"""Versioned synthetic-data configuration loading."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from backend.app.domain.base import ContractModel
from backend.app.generation.contracts import AwareDatetime, ScenarioType


class StructuringPolicy(ContractModel):
    minimum_count: int = Field(ge=2)
    lower_bound_ratio: float = Field(gt=0, lt=1)
    upper_bound_ratio: float = Field(gt=0, lt=1)


class PolicyConfig(ContractModel):
    version: str
    jurisdiction: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reporting_threshold_minor: int = Field(gt=0)
    structuring: StructuringPolicy
    high_risk_countries: list[str]
    disclaimer: str


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


def load_policy_config(path: Path) -> PolicyConfig:
    return PolicyConfig.model_validate(_read_yaml(path))


def load_generation_config(path: Path) -> GenerationConfig:
    return GenerationConfig.model_validate(_read_yaml(path))
